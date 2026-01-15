from datetime import datetime
from collections import defaultdict
import numpy as np

from vnpy.trader.utility import ArrayManager
from vnpy.trader.object import TickData, BarData
from vnpy.trader.constant import Direction, Interval

from vnpy_portfoliostrategy import StrategyTemplate, StrategyEngine
from vnpy_portfoliostrategy.utility import PortfolioBarGenerator


class TrendFollowingStrategy(StrategyTemplate):
    """ATR-RSI趋势跟踪策略"""

    author = "用Python的交易员"

    price_add = 3
    atr_window = 16
    atr_ma_window = 150
    rsi_window = 29
    rsi_entry = 11
    trend_filter_window = 158
    trailing_percent = 10

    rsi_buy = 0
    rsi_sell = 0

    # 单次交易风险敞口
    risk_per_trade = 2500
    # 敞口衰减系数，通过指数函数1-e^(-x/factor)防止一开始仓位过大，一天约400min/6h可交易
    # decay_factor = 400 * 30 * 12
    # decay_factor = 6 * 30 * 12

    parameters = [
        "price_add",
        "atr_window",
        "atr_ma_window",
        "rsi_window",
        "rsi_entry",
        "trend_filter_window",
        "risk_per_trade",
        "trailing_percent",
    ]
    variables = [
        "atr_data",
        "atr_ma",
        "rsi_buy",
        "rsi_sell",
        "rsi_data",
        "fixed_size",
    ]

    def __init__(
        self,
        strategy_engine: StrategyEngine,
        strategy_name: str,
        vt_symbols: list[str],
        setting: dict,
    ) -> None:
        """构造函数"""
        super().__init__(strategy_engine, strategy_name, vt_symbols, setting)

        self.rsi_data: dict[str, float] = {}
        self.atr_data: dict[str, float] = {}
        self.atr_ma: dict[str, float] = {}
        self.intra_trade_high: dict[str, float] = defaultdict(float)
        self.intra_trade_low: dict[str, float] = defaultdict(float)
        self.fixed_size: dict[str, int] = {}

        self.last_tick_time: datetime | None = None

        # 记录是否触发过保命止损
        self.long_stopped: dict[str, bool] = defaultdict(bool)
        self.short_stopped: dict[str, bool] = defaultdict(bool)

        # 创建每个合约的ArrayManager
        self.ams: dict[str, ArrayManager] = {}
        for vt_symbol in self.vt_symbols:
            self.ams[vt_symbol] = ArrayManager(size=200)

        self.pbg = PortfolioBarGenerator(
            self.on_bars,
            window=1,
            on_window_bars=self.on_window_bars,
            interval=Interval.HOUR,
        )

    def on_init(self) -> None:
        """策略初始化回调"""
        self.write_log("策略初始化")

        self.rsi_buy = 50 + self.rsi_entry
        self.rsi_sell = 50 - self.rsi_entry

        self.load_bars(100, interval=Interval.HOUR)

    def on_start(self) -> None:
        """策略启动回调"""
        self.write_log("策略启动")

    def on_stop(self) -> None:
        """策略停止回调"""
        self.write_log("策略停止")

    def on_tick(self, tick: TickData) -> None:
        """行情推送回调"""
        self.pbg.update_tick(tick)

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K线切片回调"""
        self.pbg.update_bars(bars)

    def on_window_bars(self, bars: dict[str, BarData]) -> None:
        """小时K线回调"""
        for vt_symbol, bar in bars.items():
            self.add_cnt(vt_symbol)
            am: ArrayManager = self.ams[vt_symbol]
            am.update_bar(bar)

            if not am.inited:
                continue

            atr_array = am.atr(self.atr_window, array=True)
            self.atr_data[vt_symbol] = atr_array[-1]
            self.atr_ma[vt_symbol] = atr_array[-self.atr_ma_window :].mean()
            self.rsi_data[vt_symbol] = am.rsi(self.rsi_window)
            # 计算均线，用于趋势过滤
            ma_trend = am.sma(self.trend_filter_window)

            # 如果RSI回归中性，说明旧趋势结束，可以解除止损封锁，允许下次开仓
            if self.rsi_data[vt_symbol] < self.rsi_buy and self.long_stopped[vt_symbol]:
                self.long_stopped[vt_symbol] = False  # 多头解锁
                self.write_log(
                    f"{bar.datetime.strftime('%Y-%m-%d %H:%M:%S')} {vt_symbol} 多头止损锁已解除"
                )

            if (
                self.rsi_data[vt_symbol] > self.rsi_sell
                and self.short_stopped[vt_symbol]
            ):
                self.short_stopped[vt_symbol] = False  # 空头解锁
                self.write_log(
                    f"{bar.datetime.strftime('%Y-%m-%d %H:%M:%S')} {vt_symbol} 空头止损锁已解除"
                )

            # 根据ATR和风险敞口计算固定仓位大小
            contract_size = self.get_size(vt_symbol)  # 获取合约乘数
            if self.atr_data[vt_symbol] > 0 and contract_size and contract_size > 0:
                self.fixed_size[vt_symbol] = int(
                    max(
                        1,
                        self.risk_per_trade
                        / (self.atr_data[vt_symbol] * contract_size),
                        # * (1 - np.exp(-self.cnt[vt_symbol] / self.decay_factor)),
                    )
                )
            else:
                self.fixed_size[vt_symbol] = 0  # 如果ATR过小，则不开仓

            current_pos = self.get_pos(vt_symbol)
            # if current_pos == 0:
            if self.atr_data[vt_symbol] > self.atr_ma[vt_symbol]:
                if (
                    self.rsi_data[vt_symbol] > self.rsi_buy
                    and bar.close_price > ma_trend
                    and not self.long_stopped[vt_symbol]  # 没有被多头止损锁住
                ):
                    self.set_target(vt_symbol, self.fixed_size[vt_symbol])
                elif (
                    self.rsi_data[vt_symbol] < self.rsi_sell
                    and bar.close_price < ma_trend
                    and not self.short_stopped[vt_symbol]  # 没有被空头止损锁住
                ):
                    self.set_target(vt_symbol, -self.fixed_size[vt_symbol])

            if current_pos > 0:
                self.intra_trade_high[vt_symbol] = max(
                    self.intra_trade_high[vt_symbol], bar.high_price
                )
                self.intra_trade_low[vt_symbol] = bar.low_price

                long_stop = self.intra_trade_high[vt_symbol] * (
                    1 - self.trailing_percent / 100
                )

                if bar.close_price <= long_stop:
                    self.set_target(vt_symbol, 0)
                    # 重置高点为当前价格
                    self.intra_trade_high[vt_symbol] = bar.high_price

            elif current_pos < 0:
                self.intra_trade_low[vt_symbol] = min(
                    self.intra_trade_low[vt_symbol], bar.low_price
                )
                self.intra_trade_high[vt_symbol] = bar.high_price

                short_stop = self.intra_trade_low[vt_symbol] * (
                    1 + self.trailing_percent / 100
                )

                if bar.close_price >= short_stop:
                    self.set_target(vt_symbol, 0)
                    # 重置低点为当前价格
                    self.intra_trade_low[vt_symbol] = bar.low_price

        self.rebalance_portfolio(bars)

        self.put_event()

    def calculate_price(
        self, vt_symbol: str, direction: Direction, reference: float
    ) -> float:
        """计算调仓委托价格（支持按需重载实现）"""
        if direction == Direction.LONG:
            price: float = reference + self.price_add * self.get_pricetick(vt_symbol)
        else:
            price = reference - self.price_add * self.get_pricetick(vt_symbol)

        return price
