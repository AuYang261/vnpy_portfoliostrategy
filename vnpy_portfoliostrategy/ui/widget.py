from vnpy.event import Event, EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.ui import QtCore, QtGui, QtWidgets
from vnpy.trader.ui.widget import (
    MsgCell,
    TimeCell,
    BaseMonitor
)
from ..base import (
    APP_NAME,
    EVENT_PORTFOLIO_LOG,
    EVENT_PORTFOLIO_STRATEGY
)
from ..engine import StrategyEngine
from ..locale import _


class PortfolioStrategyManager(QtWidgets.QWidget):
    """组合策略界面"""

    signal_log: QtCore.Signal = QtCore.Signal(Event)
    signal_strategy: QtCore.Signal = QtCore.Signal(Event)

    def __init__(self, main_engine: MainEngine, event_engine: EventEngine) -> None:
        """构造函数"""
        super().__init__()

        self.main_engine: MainEngine = main_engine
        self.event_engine: EventEngine = event_engine
        self.strategy_engine: StrategyEngine = main_engine.get_engine(APP_NAME)

        self.managers: dict[str, StrategyManager] = {}

        self.init_ui()
        self.register_event()
        self.strategy_engine.init_engine()
        self.update_class_combo()

    def init_ui(self) -> None:
        """初始化界面"""
        self.setWindowTitle(_("组合策略"))

        # Create widgets
        self.class_combo: QtWidgets.QComboBox = QtWidgets.QComboBox()

        add_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("添加策略"))
        add_button.clicked.connect(self.add_strategy)

        init_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("全部初始化"))
        init_button.clicked.connect(self.strategy_engine.init_all_strategies)

        start_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("全部启动"))
        start_button.clicked.connect(self.strategy_engine.start_all_strategies)

        stop_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("全部停止"))
        stop_button.clicked.connect(self.strategy_engine.stop_all_strategies)

        clear_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("清空日志"))
        clear_button.clicked.connect(self.clear_log)

        self.scroll_layout: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        self.scroll_layout.addStretch()

        scroll_widget: QtWidgets.QWidget = QtWidgets.QWidget()
        scroll_widget.setLayout(self.scroll_layout)

        scroll_area: QtWidgets.QScrollArea = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(scroll_widget)

        self.log_monitor: LogMonitor = LogMonitor(self.main_engine, self.event_engine)

        hbox1: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        hbox1.addWidget(self.class_combo)
        hbox1.addWidget(add_button)
        hbox1.addStretch()
        hbox1.addWidget(init_button)
        hbox1.addWidget(start_button)
        hbox1.addWidget(stop_button)
        hbox1.addWidget(clear_button)

        hbox2: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        hbox2.addWidget(scroll_area)
        hbox2.addWidget(self.log_monitor)

        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addLayout(hbox1)
        vbox.addLayout(hbox2)

        self.setLayout(vbox)

    def update_class_combo(self) -> None:
        """更新策略类名显示控件"""
        self.class_combo.addItems(
            self.strategy_engine.get_all_strategy_class_names()
        )

    def register_event(self) -> None:
        """注册事件引擎"""
        self.signal_strategy.connect(self.process_strategy_event)

        self.event_engine.register(
            EVENT_PORTFOLIO_STRATEGY, self.signal_strategy.emit
        )

    def process_strategy_event(self, event: Event) -> None:
        """策略事件推送"""
        data: dict = event.data
        strategy_name: str = data["strategy_name"]

        if strategy_name in self.managers:
            manager: StrategyManager = self.managers[strategy_name]
            manager.update_data(data)
        else:
            manager = StrategyManager(self, self.strategy_engine, data)
            self.scroll_layout.insertWidget(0, manager)
            self.managers[strategy_name] = manager

    def remove_strategy(self, strategy_name: str) -> None:
        """移除策略"""
        manager: StrategyManager = self.managers.pop(strategy_name)
        manager.deleteLater()

    def add_strategy(self) -> None:
        """添加策略"""
        class_name: str = str(self.class_combo.currentText())
        if not class_name:
            return

        parameters: dict = self.strategy_engine.get_strategy_class_parameters(class_name)
        editor: SettingEditor = SettingEditor(parameters, class_name=class_name)
        n: int = editor.exec_()

        if n == editor.DialogCode.Accepted:
            setting: dict = editor.get_setting()
            vt_symbols: list[str] = setting.pop("vt_symbols").split(",")
            strategy_name: str = setting.pop("strategy_name")

            self.strategy_engine.add_strategy(
                class_name, strategy_name, vt_symbols, setting
            )

    def clear_log(self) -> None:
        """清除日志"""
        self.log_monitor.setRowCount(0)

    def show(self) -> None:
        """最大化显示"""
        self.showMaximized()


class StrategyManager(QtWidgets.QFrame):
    """策略控制控件"""

    def __init__(
        self,
        strategy_manager: PortfolioStrategyManager,
        strategy_engine: StrategyEngine,
        data: dict
    ) -> None:
        """构造函数"""
        super().__init__()

        self.strategy_manager: PortfolioStrategyManager = strategy_manager
        self.strategy_engine: StrategyEngine = strategy_engine

        self.strategy_name: str = data["strategy_name"]
        self._data: dict = data

        self.init_ui()

    def init_ui(self) -> None:
        """初始化界面"""
        self.setFrameShape(self.Shape.Box)
        self.setLineWidth(1)

        self.init_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("初始化"))
        self.init_button.clicked.connect(self.init_strategy)

        self.start_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("启动"))
        self.start_button.clicked.connect(self.start_strategy)
        self.start_button.setEnabled(False)

        self.stop_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("停止"))
        self.stop_button.clicked.connect(self.stop_strategy)
        self.stop_button.setEnabled(False)

        self.edit_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("编辑"))
        self.edit_button.clicked.connect(self.edit_strategy)

        self.remove_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("移除"))
        self.remove_button.clicked.connect(self.remove_strategy)

        self.cover_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("平仓"))
        self.cover_button.clicked.connect(self.cover_strategy)
        self.cover_button.setEnabled(False)

        strategy_name: str = self._data["strategy_name"]
        class_name: str = self._data["class_name"]
        author: str = self._data["author"]

        label_text: str = (
            f"{strategy_name}  -  ({class_name} by {author})"
        )
        label: QtWidgets.QLabel = QtWidgets.QLabel(label_text)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        self.parameters_monitor: DataMonitor = DataMonitor(self._data["parameters"])
        self.default_variables_monitor: DataMonitor = DataMonitor(
            self._data["default_variables"]
        )
        self.variables_monitor: DataMonitor = DataMonitor(self._data["variables"])

        for table in (
            self.parameters_monitor,
            self.default_variables_monitor,
            self.variables_monitor,
        ):
            table.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Minimum,
            )
            table.adjust_height()

        hbox: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        hbox.addWidget(self.init_button)
        hbox.addWidget(self.start_button)
        hbox.addWidget(self.stop_button)
        hbox.addWidget(self.edit_button)
        hbox.addWidget(self.remove_button)
        hbox.addWidget(self.cover_button)

        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addWidget(label)
        vbox.addLayout(hbox)
        vbox.addWidget(self.parameters_monitor)
        vbox.addWidget(self.default_variables_monitor)
        vbox.addWidget(self.variables_monitor)
        self.setLayout(vbox)

    def update_data(self, data: dict) -> None:
        """更新策略数据"""
        self._data = data

        self.parameters_monitor.update_data(data["parameters"])
        self.default_variables_monitor.update_data(data["default_variables"])
        self.variables_monitor.update_data(data["variables"])

        self.parameters_monitor.adjust_height()
        self.default_variables_monitor.adjust_height()
        self.variables_monitor.adjust_height()

        # 更新按钮状态
        default_variables: dict = data["default_variables"]
        inited: bool = default_variables["inited"]
        trading: bool = default_variables["trading"]

        if not inited:
            return

        if trading:
            self.init_button.setEnabled(False)
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.edit_button.setEnabled(False)
            self.remove_button.setEnabled(False)
            self.cover_button.setEnabled(True)
        else:
            self.init_button.setEnabled(True)
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.edit_button.setEnabled(True)
            self.remove_button.setEnabled(True)
            self.cover_button.setEnabled(False)

    def init_strategy(self) -> None:
        """初始化策略"""
        self.strategy_engine.init_strategy(self.strategy_name)

    def start_strategy(self) -> None:
        """启动策略"""
        self.strategy_engine.start_strategy(self.strategy_name)

    def stop_strategy(self) -> None:
        """停止策略"""
        self.strategy_engine.stop_strategy(self.strategy_name)

    def edit_strategy(self) -> None:
        """编辑策略"""
        strategy_name: str = self._data["strategy_name"]

        parameters: dict = self.strategy_engine.get_strategy_parameters(strategy_name)
        editor: SettingEditor = SettingEditor(parameters, strategy_name=strategy_name)
        n: int = editor.exec_()

        if n == editor.DialogCode.Accepted:
            setting: dict = editor.get_setting()
            self.strategy_engine.edit_strategy(strategy_name, setting)

    def remove_strategy(self) -> None:
        """移除策略"""
        result: bool = self.strategy_engine.remove_strategy(self.strategy_name)

        # 只移除在策略引擎被成功移除的策略
        if result:
            self.strategy_manager.remove_strategy(self.strategy_name)

    def cover_strategy(self) -> None:
        """移除策略"""
        self.strategy_engine.close_all_positions(self.strategy_name)


class DataMonitor(QtWidgets.QTableWidget):
    """策略监控组件"""

    def __init__(self, data: dict) -> None:
        """构造函数"""
        super().__init__()

        self._data: dict = data
        self.cells: dict = {}

        self.init_ui()

    def init_ui(self) -> None:
        """初始化界面"""
        labels: list = list(self._data.keys())
        self.setColumnCount(len(labels))
        self.setHorizontalHeaderLabels(labels)

        self.setRowCount(1)
        self.verticalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)

        # 开启单元格自动换行
        self.setWordWrap(True)

        for column, name in enumerate(self._data.keys()):
            value = self._data[name]

            cell: QtWidgets.QTableWidgetItem = QtWidgets.QTableWidgetItem(str(value))
            cell.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

            self.setItem(0, column, cell)
            self.cells[name] = cell

        self.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        # 初始根据内容调整行高
        self.resizeRowsToContents()
        self.adjust_height()

    def adjust_height(self) -> None:
        """根据当前内容计算并设置所需最小高度，使其随多行文本自适应"""
        # 只有一行数据：行高 + 表头高 + 边框和滚动条的预留
        row_heights = sum(self.rowHeight(r) for r in range(self.rowCount()))
        header_h = (
            self.horizontalHeader().height()
            if self.horizontalHeader().isVisible()
            else 0
        )
        frame = self.frameWidth() * 2
        # 额外留一点空间避免裁剪
        extra = 0
        needed_h = row_heights + header_h + frame + extra
        self.setFixedHeight(needed_h)

    def update_data(self, data: dict) -> None:
        """更新数据"""
        for name, value in data.items():
            cell: QtWidgets.QTableWidgetItem = self.cells[name]
            if isinstance(value, dict):
                lines: list[str] = [
                    f"{k}: {v:.2f}" if isinstance(v, float) else f"{k}: {v}"
                    for k, v in value.items()
                ]
                lines.sort()
                value_str = "\n".join(lines)
            elif isinstance(value, float):
                value_str = f"{value:.2f}"
            else:
                value_str = str(value)
            cell.setText(value_str)
        # 依据最新内容调整本行高度
        self.resizeRowsToContents()

class LogMonitor(BaseMonitor):
    """日志监控组件"""

    event_type: str = EVENT_PORTFOLIO_LOG
    data_key: str = ""
    sorting: bool = False

    headers: dict = {
        "time": {"display": _("时间"), "cell": TimeCell, "update": False},
        "msg": {"display": _("信息"), "cell": MsgCell, "update": False},
    }

    def init_ui(self) -> None:
        """初始化界面"""
        super().init_ui()

        self.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch
        )

    def insert_new_row(self, data: dict) -> None:
        """插入新行"""
        super().insert_new_row(data)
        self.resizeRowToContents(0)


class SettingEditor(QtWidgets.QDialog):
    """配置编辑框"""

    def __init__(
        self, parameters: dict, strategy_name: str = "", class_name: str = ""
    ) -> None:
        """构造函数"""
        super().__init__()

        self.parameters: dict = parameters
        self.strategy_name: str = strategy_name
        self.class_name: str = class_name

        self.edits: dict = {}

        self.init_ui()

    def init_ui(self) -> None:
        """初始化界面"""
        form: QtWidgets.QFormLayout = QtWidgets.QFormLayout()

        if self.class_name:
            self.setWindowTitle(_("添加策略：{}").format(self.class_name))
            button_text: str = _("添加")
            parameters: dict = {"strategy_name": "", "vt_symbols": ""}
            parameters.update(self.parameters)
        else:
            self.setWindowTitle(_("参数编辑：{}").format(self.strategy_name))
            button_text = _("确定")
            parameters = self.parameters

        for name, value in parameters.items():
            type_ = type(value)

            edit: QtWidgets.QLineEdit = QtWidgets.QLineEdit(str(value))
            if type_ is int:
                validator: QtGui.QIntValidator = QtGui.QIntValidator()
                edit.setValidator(validator)
            elif type_ is float:
                validator = QtGui.QDoubleValidator()
                edit.setValidator(validator)

            form.addRow(f"{name} {type_}", edit)

            self.edits[name] = (edit, type_)

        button: QtWidgets.QPushButton = QtWidgets.QPushButton(button_text)
        button.clicked.connect(self.accept)
        form.addRow(button)

        self.setLayout(form)

    def get_setting(self) -> dict:
        """获取策略配置"""
        setting: dict = {}

        if self.class_name:
            setting["class_name"] = self.class_name

        for name, tp in self.edits.items():
            edit, type_ = tp
            value_text = edit.text()

            if type_ is bool:
                if value_text == "True":
                    value: bool = True
                else:
                    value = False
            else:
                value = type_(value_text)

            setting[name] = value

        return setting
