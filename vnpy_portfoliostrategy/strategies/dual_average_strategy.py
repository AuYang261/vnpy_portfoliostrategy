from datetime import datetime
from collections import defaultdict
import numpy as np

from vnpy.trader.utility import ArrayManager
from vnpy.trader.object import TickData, BarData
from vnpy.trader.constant import Direction, Interval

from vnpy_portfoliostrategy import StrategyTemplate, StrategyEngine
from vnpy_portfoliostrategy.utility import PortfolioBarGenerator


class DoubleMaPortfolioStrategy(StrategyTemplate):
    """
    多品种双均线组合策略
    1. 使用快慢均线交叉作为信号
    2. 使用ATR进行风险归一化仓位管理
    3. 适用于PortfolioStrategy模块
    """

    author = "量化交易员"

    # 策略参数
    fast_window = 13  # 快线周期
    slow_window = 235  # 慢线周期
    atr_window = 20  # ATR周期（用于计算仓位）
    risk_per_trade = 4000  # 单笔交易风险敞口（元）
    price_add = 3  # 下单超价

    fixed_size_min = 1  # 最小开仓手数

    # 变量列表
    parameters = [
        "fast_window",
        "slow_window",
        "atr_window",
        "risk_per_trade",
        "price_add",
    ]

    variables = ["fast_ma_data", "slow_ma_data", "atr_data", "fixed_size"]

    def __init__(
        self,
        strategy_engine: StrategyEngine,
        strategy_name: str,
        vt_symbols: list[str],
        setting: dict,
    ) -> None:
        """构造函数"""
        super().__init__(strategy_engine, strategy_name, vt_symbols, setting)

        # 状态字典
        self.fast_ma_data: dict[str, float] = defaultdict(float)
        self.slow_ma_data: dict[str, float] = defaultdict(float)
        self.atr_data: dict[str, float] = defaultdict(float)
        self.fixed_size: dict[str, int] = defaultdict(int)

        self.interval = Interval.HOUR

        # 每一个品种对应的ArrayManager
        self.ams: dict[str, ArrayManager] = {}
        for vt_symbol in self.vt_symbols:
            # size设为slow_window的2倍确保足够计算
            self.ams[vt_symbol] = ArrayManager(
                size=max(self.slow_window, self.atr_window) + 20
            )

        # 创建K线合成器
        self.pbg = PortfolioBarGenerator(
            self.on_bars,
            window=1,
            on_window_bars=self.on_window_bars,
            interval=self.interval,
        )
        self.last_balance = 0

    def on_init(self) -> None:
        """策略初始化回调"""
        self.write_log("双均线组合策略初始化")
        # 加载100天的数据
        self.load_bars(100, interval=self.interval)

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
        """K线切片回调（分钟）"""
        self.pbg.update_bars(bars)
        # 有未提交的订单连续5分钟都没提交成功，重新发起提交
        if len(self.active_orderids) > 0:
            if self.last_balance > 5:
                self.rebalance_portfolio(bars)
                self.last_balance = 0
            else:
                self.last_balance += 1
        else:
            self.last_balance = 0

    def on_window_bars(self, bars: dict[str, BarData]) -> None:
        """小时K线逻辑"""
        for vt_symbol, bar in bars.items():
            am: ArrayManager = self.ams[vt_symbol]
            am.update_bar(bar)

            if not am.inited:
                continue

            # 1. 计算指标
            fast_ma: np.ndarray = am.sma(self.fast_window, array=True)  # type: ignore
            slow_ma: np.ndarray = am.sma(self.slow_window, array=True)  # type: ignore
            atr_val: float = am.atr(self.atr_window)  # type: ignore

            self.fast_ma_data[vt_symbol] = fast_ma[-1]
            self.slow_ma_data[vt_symbol] = slow_ma[-1]
            self.atr_data[vt_symbol] = atr_val

            # 2. 计算仓位 (基于ATR的风险管理)
            contract_size = self.get_size(vt_symbol)
            if atr_val > 0 and contract_size > 0:
                # 仓位 = 风险总额 / (单手波动价值)
                # 单手波动价值 = ATR * 合约乘数
                raw_size = self.risk_per_trade / (atr_val * contract_size)
                self.fixed_size[vt_symbol] = int(max(self.fixed_size_min, raw_size))
            else:
                self.fixed_size[vt_symbol] = 0

            # 3. 信号判断
            current_pos = self.get_pos(vt_symbol)

            # 金叉：快线上穿慢线
            cross_over = (fast_ma[-1] > slow_ma[-1]) and (fast_ma[-2] <= slow_ma[-2])
            # 死叉：快线下穿慢线
            cross_below = (fast_ma[-1] < slow_ma[-1]) and (fast_ma[-2] >= slow_ma[-2])

            # 执行目标仓位设置
            if cross_over:
                self.set_target(vt_symbol, self.fixed_size[vt_symbol])
            elif cross_below:
                self.set_target(vt_symbol, -self.fixed_size[vt_symbol])

            # 注意：双均线通常是全时在场策略，如果不需要全时在场，
            # 可以通过增加一个“趋势过滤”或“平仓规则”来修改 set_target

        # 4. 组合下单再平衡
        self.rebalance_portfolio(bars)
        self.last_balance = 0
        self.put_event()

    def calculate_price(
        self, vt_symbol: str, direction: Direction, reference: float
    ) -> float:
        """
        重载计算委托价格，实现超价下单确保成交
        """
        pricetick = self.get_pricetick(vt_symbol)
        if direction == Direction.LONG:
            price = reference + self.price_add * pricetick
        else:
            price = reference - self.price_add * pricetick
        return price
