from abc import ABC, abstractmethod
from threading import Thread
import time
from copy import copy
from collections import defaultdict
from typing import Any, cast
import re

from vnpy.trader.constant import Interval, Direction, Offset
from vnpy.trader.object import BarData, TickData, OrderData, TradeData

from .base import EngineType


class StrategyTemplate(ABC):
    """组合策略模板"""

    author: str = ""
    parameters: list = []
    default_variables: list = []
    variables: list = []

    def __init__(
        self,
        strategy_engine: Any,
        strategy_name: str,
        vt_symbols: list[str],
        setting: dict,
    ) -> None:
        """构造函数"""
        self.strategy_engine: Any = strategy_engine
        self.strategy_name: str = strategy_name
        self.vt_symbols: list[str] = vt_symbols

        # 状态控制变量
        self.inited: bool = False
        self.trading: bool = False

        # 持仓数据字典
        self.pos_data: dict[str, int] = defaultdict(int)  # 实际持仓
        self.target_data: dict[str, int] = defaultdict(int)  # 目标持仓

        # 委托缓存容器
        self.orders: dict[str, OrderData] = {}
        self.active_orderids: set[str] = set()

        self.default_variables: list = [
            "inited",
            "trading",
            "pos_data",
            "target_data",
        ]

        # 设置策略参数
        self.update_setting(setting)

        # 定时打印主力合约信息log线程
        self.dominant_log_thread: Thread = Thread(
            target=self._log_dominant_thread_func, daemon=True
        )
        self.dominant_log_thread.start()

    def update_setting(self, setting: dict) -> None:
        """设置策略参数"""
        for name in self.parameters:
            if name in setting:
                setattr(self, name, setting[name])

    @classmethod
    def get_class_parameters(cls) -> dict:
        """查取策略默认参数"""
        class_parameters: dict = {}
        for name in cls.parameters:
            class_parameters[name] = getattr(cls, name)
        return class_parameters

    def get_parameters(self) -> dict:
        """查询策略参数"""
        strategy_parameters: dict = {}
        for name in self.parameters:
            strategy_parameters[name] = getattr(self, name)
        return strategy_parameters

    def get_variables(self) -> dict:
        """查询策略变量"""
        strategy_variables: dict = {}
        for name in self.variables:
            strategy_variables[name] = getattr(self, name)
        return strategy_variables

    def get_default_variables(self) -> dict:
        """查询策略默认变量"""
        strategy_variables: dict = {}
        for name in self.default_variables:
            strategy_variables[name] = getattr(self, name)
        return strategy_variables

    def get_data(self) -> dict:
        """查询策略状态数据"""
        strategy_data: dict = {
            "strategy_name": self.strategy_name,
            "vt_symbols": self.vt_symbols,
            "class_name": self.__class__.__name__,
            "author": self.author,
            "parameters": self.get_parameters(),
            "default_variables": self.get_default_variables(),
            "variables": self.get_variables(),
            "pos_data": self.pos_data,
        }
        return strategy_data

    @abstractmethod
    def on_init(self) -> None:
        """策略初始化回调"""
        return

    def on_start(self) -> None:
        """策略启动回调"""
        return

    def on_stop(self) -> None:
        """策略停止回调"""
        return

    def on_tick(self, tick: TickData) -> None:
        """行情推送回调"""
        return

    @abstractmethod
    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K线切片回调"""
        return

    def update_trade(self, trade: TradeData) -> None:
        """成交数据更新"""
        if trade.direction == Direction.LONG:
            self.pos_data[trade.vt_symbol] += trade.volume
        else:
            self.pos_data[trade.vt_symbol] -= trade.volume

    def update_order(self, order: OrderData) -> None:
        """委托数据更新"""
        self.orders[order.vt_orderid] = order

        if not order.is_active() and order.vt_orderid in self.active_orderids:
            self.active_orderids.remove(order.vt_orderid)

    def buy(
        self,
        vt_symbol: str,
        price: float,
        volume: float,
        lock: bool = False,
        net: bool = False,
    ) -> list[str]:
        """买入开仓"""
        return self.send_order(
            vt_symbol, Direction.LONG, Offset.OPEN, price, volume, lock, net
        )

    def sell(
        self,
        vt_symbol: str,
        price: float,
        volume: float,
        lock: bool = False,
        net: bool = False,
    ) -> list[str]:
        """卖出平仓"""
        return self.send_order(
            vt_symbol, Direction.SHORT, Offset.CLOSE, price, volume, lock, net
        )

    def short(
        self,
        vt_symbol: str,
        price: float,
        volume: float,
        lock: bool = False,
        net: bool = False,
    ) -> list[str]:
        """卖出开仓"""
        return self.send_order(
            vt_symbol, Direction.SHORT, Offset.OPEN, price, volume, lock, net
        )

    def cover(
        self,
        vt_symbol: str,
        price: float,
        volume: float,
        lock: bool = False,
        net: bool = False,
    ) -> list[str]:
        """买入平仓"""
        return self.send_order(
            vt_symbol, Direction.LONG, Offset.CLOSE, price, volume, lock, net
        )

    def send_order(
        self,
        vt_symbol: str,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
        lock: bool = False,
        net: bool = False,
    ) -> list[str]:
        """发送委托"""
        if self.trading:
            vt_orderids: list = self.strategy_engine.send_order(
                self, vt_symbol, direction, offset, price, volume, lock, net
            )

            for vt_orderid in vt_orderids:
                self.active_orderids.add(vt_orderid)

            return vt_orderids
        else:
            return []

    def cancel_order(self, vt_orderid: str) -> None:
        """撤销委托"""
        if self.trading:
            self.strategy_engine.cancel_order(self, vt_orderid)

    def cancel_all(self) -> None:
        """全撤活动委托"""
        # 撤单失败，比如可能是根本没有提交成功，就会一直反复撤单，同时也提交不了新的委托且没有提示
        # 可改进：提交成功和撤单成功都要有反馈，比如发一个event，确认成功再加入或移除出active_orderids
        # 这样需要修改交易接口模块vnctptdapi，是一个动态链接库，不好改，但理论上这个事件是vnpy的概念，怎么跟交易接口绑定呢？
        # 再检查一下EVENT_ORDER事件的触发时机，是不是可以用来确认撤单成功与否
        # 或者检查一下，确保send_order要确认提交成功后才加入active_orderids，目前send_order即使提交失败也加入了active_orderids
        for vt_orderid in list(self.active_orderids):
            self.cancel_order(vt_orderid)

    def get_pos(self, vt_symbol: str) -> int:
        """查询当前持仓"""
        return self.pos_data.get(vt_symbol, 0)

    def get_target(self, vt_symbol: str) -> int:
        """查询目标仓位"""
        return self.target_data[vt_symbol]

    def set_target(self, vt_symbol: str, target: int) -> None:
        """设置目标仓位"""
        self.target_data[vt_symbol] = target

    def rebalance_portfolio(self, bars: dict[str, BarData]) -> None:
        """基于目标执行调仓交易"""
        self.cancel_all()

        # 只发出当前K线切片有行情的合约的委托
        for vt_symbol, bar in bars.items():
            # 计算仓差
            target: int = self.get_target(vt_symbol)
            pos: int = self.get_pos(vt_symbol)
            diff: int = target - pos

            # 多头
            if diff > 0:
                # 计算多头委托价
                order_price: float = self.calculate_price(
                    vt_symbol, Direction.LONG, bar.close_price
                )

                # 计算买平和买开数量
                cover_volume: int = 0
                buy_volume: int = 0

                if pos < 0:
                    cover_volume = min(diff, abs(pos))
                    buy_volume = diff - cover_volume
                else:
                    buy_volume = diff

                # 发出对应委托
                if cover_volume:
                    self.cover(vt_symbol, order_price, cover_volume)

                if buy_volume:
                    self.buy(vt_symbol, order_price, buy_volume)
            # 空头
            elif diff < 0:
                # 计算空头委托价
                order_price = self.calculate_price(
                    vt_symbol, Direction.SHORT, bar.close_price
                )

                # 计算卖平和卖开数量
                sell_volume: int = 0
                short_volume: int = 0

                if pos > 0:
                    sell_volume = min(abs(diff), pos)
                    short_volume = abs(diff) - sell_volume
                else:
                    short_volume = abs(diff)

                # 发出对应委托
                if sell_volume:
                    self.sell(vt_symbol, order_price, sell_volume)

                if short_volume:
                    self.short(vt_symbol, order_price, short_volume)

    def calculate_price(
        self, vt_symbol: str, direction: Direction, reference: float
    ) -> float:
        """计算调仓委托价格（支持按需重载实现）"""
        return reference

    def get_order(self, vt_orderid: str) -> OrderData | None:
        """查询委托数据"""
        return self.orders.get(vt_orderid, None)

    def get_all_active_orderids(self) -> list[OrderData]:
        """获取全部活动状态的委托号"""
        return list(self.active_orderids)

    def write_log(self, msg: str) -> None:
        """记录日志"""
        self.strategy_engine.write_log(msg, self)

    def get_engine_type(self) -> EngineType:
        """查询引擎类型"""
        return cast(EngineType, self.strategy_engine.get_engine_type())

    def get_pricetick(self, vt_symbol: str) -> float:
        """查询合约最小价格跳动"""
        return cast(float, self.strategy_engine.get_pricetick(self, vt_symbol))

    def get_size(self, vt_symbol: str) -> int:
        """查询合约乘数"""
        return cast(int, self.strategy_engine.get_size(self, vt_symbol))

    def get_total_capital(self) -> float:
        """查询总资金"""
        return cast(float, self.strategy_engine.get_total_capital(self))

    def load_bars(self, days: int, interval: Interval = Interval.MINUTE) -> None:
        """加载历史K线数据来执行初始化"""
        self.strategy_engine.load_bars(self, days, interval)

    def put_event(self) -> None:
        """推送策略数据更新事件"""
        if self.inited:
            self.strategy_engine.put_strategy_event(self)

    def send_email(self, msg: str) -> None:
        """发送邮件信息"""
        if self.inited:
            self.strategy_engine.send_email(msg, self)

    def sync_data(self) -> None:
        """同步策略状态数据到文件"""
        if self.trading:
            self.strategy_engine.sync_strategy_data(self)

    def close_all_positions(self) -> None:
        """平掉所有持仓"""
        self.cancel_all()

        for vt_symbol in self.vt_symbols:
            self.set_target(vt_symbol, 0)
        self.write_log(
            "target_data置为0，下一次on_bar平掉所有持仓，再次初始化恢复target_data"
        )

    def query_dominant(self) -> list[str] | None:
        """查询vt_symbols中各代码的主力合约代码"""
        import rqdatac

        dominant_list: list[str] = []
        for vt_symbol in self.vt_symbols:
            symbol, exchange = vt_symbol.split(".")
            # 提取前缀代码
            symbol = "".join(filter(str.isalpha, symbol))
            symbol = symbol.upper()
            try:
                date = rqdatac.get_future_latest_trading_date().strftime("%Y%m%d")
            except Exception as ex:
                self.write_log(f"获取最新交易日期失败，错误信息：{ex}")
                return None
            try:
                rq_symbol_serial = rqdatac.futures.get_dominant(symbol, start_date=date)
            except Exception as ex:
                self.write_log(f"查询主力合约失败，错误信息：{ex}")
                return None
            if rq_symbol_serial is not None and not rq_symbol_serial.empty:
                rq_symbol: str = rq_symbol_serial.loc[date]
                if exchange == "CZCE":
                    # 删掉第一个数字
                    rq_symbol = re.sub(r"\d", "", rq_symbol, count=1)
                elif exchange in ["DCE", "SHFE"]:
                    # 改为小写
                    rq_symbol = rq_symbol.lower()
                dominant_vt_symbol = f"{rq_symbol}.{exchange}"
                dominant_list.append(dominant_vt_symbol)

        return dominant_list

    def _log_dominant_thread_func(self) -> None:
        """定时打印主力合约信息log线程函数"""
        last = None
        while True:
            now = time.localtime()
            # 每天9点后打印一次
            if last is None or (now.tm_mday != last.tm_mday and now.tm_hour >= 9):
                dominant_list = self.query_dominant()
                if dominant_list:
                    dominant_str = ", ".join(dominant_list)
                    self.write_log(f"主力合约：{dominant_str}")
                    print(f"主力合约：{dominant_str}")
                    # 改为全大写方便比较
                    dominant_list = list(map(lambda s: s.upper(), dominant_list))
                    for vt_symbol in self.vt_symbols:
                        if vt_symbol.upper() not in dominant_list:
                            self.write_log(f"注意，当前{vt_symbol} 不是主力合约")
                    last = now
            # 间隔1h检查
            time.sleep(60 * 60)
