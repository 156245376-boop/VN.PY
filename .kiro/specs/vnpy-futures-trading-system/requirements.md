# Requirements Document

## Introduction

本文档定义一套基于 vn.py 的个人自用国内期货交易与回测系统的需求。系统运行于单机 Windows 环境,采用 Python 实现,以**双进程**形态运行:数据录制与策略执行为 headless 常驻进程,VN Trader GUI 作为可随时开关的监控外壳。

系统覆盖 CTP 行情接入、tick 与 1 分钟 K 线落库、数据质量保障与历史回补、主力连续合约构造、策略开发框架、单品种与多品种组合回测、参数优化、实盘与模拟盘全自动策略运行、委托与持仓管理、风控、合约到期换月、日志监控告警、配置管理。

核心设计原则:

- **自建数据资产为主**:实时行情由自建通道落库,外部免费数据源(TQSDK、akshare)仅用于历史回补与补缺,系统不依赖收费数据服务。数据来源须显式记录,自建通道记录优先于外部源。
- **原始层不可变**:采集到的原始数据永不编辑、永不删除;所有清洗与解释产物可从原始层完整重建。
- **回测与实盘共用同一份计算**:手续费、保证金、开平决策由同一批函数服务两条路径,不存在两份实现。
- **策略与框架解耦**:策略为纯逻辑类,不依赖任何交易框架的基类,以便更换回测引擎时无需改动策略源码。
- **模块物理隔离**:每个模块位于独立子文件夹,对外仅暴露显式接口,依赖关系构成有向无环图。异步行情与回报走 EventEngine,查询类交互走显式函数调用。
- **面向订单流的可扩展性**:tick 落库范围由配置清单控制,未来扩展订单流研究只需扩大清单,不修改架构与代码结构。
- **参考数据带生效日期**:费率、保证金、交易时段、合约乘数等市场事实随时间变化,须按生效日期版本化存储,回测须使用当时生效的取值。

明确不在本系统范围内的内容:自研 K 线图表绘制、画线工具、指标可视化界面;看盘由外部行情软件(快期、文华财经)承担。机器学习信号生成不在当前范围内,但模块划分须为其预留接入位置。

以下默认值已写入需求,可在评审时直接修改:单账户单实例运行、单机 Windows 部署、**风控约束内全自动下单**、回测按 1 分钟 K 线撮合并建模滑点与手续费。

## Glossary

- **Trading_System**: 本文档定义的完整期货交易与回测系统,由下列各子系统组成。
- **Recorder_Process**: headless 常驻进程,负责 CTP 行情接入、tick 落库与 1 分钟 K 线合成,不依赖图形界面,可独立部署于常开机器。
- **Live_Process**: headless 常驻进程,负责策略运行、委托执行、风控与持仓对账。
- **Monitor_Shell**: 只读监控外壳,展示运行状态与告警。可基于 VN Trader 图形界面实现,可随时启动与关闭,其崩溃或退出不影响 Recorder_Process 与 Live_Process。
- **State_Snapshot**: Recorder_Process 与 Live_Process 周期性写出的运行状态快照文件,Monitor_Shell 的唯一数据来源。写入方只写不读,读取方只读不写。
- **Market_Data_Gateway**: 通过 CTP 接口接收期货行情与交易回报的接入子系统。
- **Subscription_Manager**: 管理合约订阅清单与订阅动作的子系统。
- **Trading_Session_Calendar**: 提供交易日与交易时段(含夜盘)判定的子系统。
- **Tick_Recorder**: 将 tick 数据按配置清单写入数据库的子系统。
- **Bar_Aggregator**: 将 CTP 快照聚合为 1 分钟 K 线的子系统。
- **Data_Store**: `data` Module_Package 拥有的市场数据持久化子系统,对外提供两组接口:一组实现 vn.py `BaseDatabase` 供回测引擎读取 Bar,另一组承载质量报告、异常标记、Provenance_Table 与 Ingest_Manifest。默认实现为 Parquet 文件加 DuckDB 查询层;不持有策略状态与告警记录。
- **Reference_Data_Store**: `meta` Module_Package 拥有的参考数据端口,按生效日期读写合约、交易日历、Trading_Session、费率、保证金与结算价等市场事实。调用方依赖 `meta` 的公开协议,不依赖 `data` 的实现。
- **Runtime_State_Store**: `runtime` Module_Package 拥有的实盘状态端口,持久化策略参数、策略内部变量及其 schema 版本;默认落入 `runtime/state.db`。
- **Raw_Layer**: 原始数据层,保存各数据源返回的原始内容,不可编辑、不可删除、只追加。
- **Curated_Layer**: 清洗层,由 Raw_Layer 完整重建而来的可用数据集,允许整分区重写。
- **Ingest_Manifest**: 采集台账,记录每次采集的键、路径、行数、校验和、采集时间与数据源版本。
- **Provenance_Table**: 数据来源表,以合约代码、交易所、周期、时间戳为键,记录该条 Bar 的数据来源与写入时间,用于判定回补时的取舍优先级。
- **Data_Version**: Curated_Layer 每次构建产生的版本标识,回测结果须携带该标识以保证可追溯。
- **Data_Quality_Checker**: 检测历史数据缺失与异常值的子系统。
- **Backfill_Service**: 执行历史数据回补的子系统,支持自动触发与手动触发。
- **History_Import_Adapter**: 将外部历史数据源(TQSDK、akshare)数据转换为系统内部数据结构并导入的适配子系统。
- **Continuous_Series_Builder**: 构造主力连续合约序列的子系统,产出换月映射与复权序列。
- **Roll_Map**: 交易日到该日活跃合约代码的映射表。
- **Roll_Event**: 一次换月记录,包含换月交易日、换出合约、换入合约、换月成本。
- **Adjustment_Method**: 换月复权方式,取值为无复权、前复权、后复权、比例复权之一。
- **Settlement_Price**: 交易所公布的当日结算价,用于每日盯市、保证金计算与单日盈亏判定,区别于收盘价。
- **Strategy**: 策略纯逻辑类,仅依赖 numpy 与系统自有数据结构,不依赖任何交易框架基类。以目标持仓表达交易意图。
- **Strategy_Context**: 引擎向 Strategy 提供的运行期接口协议,包含时间、行情序列、持仓查询、目标持仓设置。
- **Engine_Adapter**: 将 Strategy 适配到具体回测或实盘引擎的转换层,是系统内唯一同时依赖交易框架与 Strategy 的代码位置。
- **Target_Position**: 策略期望在某合约上持有的净持仓手数,正数为多头,负数为空头。
- **Strategy_Framework**: Strategy 的开发、加载与参数管理框架子系统。
- **Backtest_Engine**: 执行历史回测撮合的子系统。
- **Performance_Analyzer**: 计算回测与实盘绩效指标的子系统。
- **Parameter_Optimizer**: 执行策略参数优化搜索的子系统。
- **Live_Trading_Engine**: 在实盘或模拟盘环境驱动策略运行的子系统。
- **Order_Manager**: 管理委托生命周期与成交回报的子系统。
- **Account_Service**: 提供持仓与资金查询的子系统。
- **Risk_Manager**: 在委托发出前执行风控校验的子系统。
- **Cost_Model**: 计算手续费、滑点与保证金占用的子系统,由 Backtest_Engine 与 Live_Trading_Engine 共同调用同一批函数。
- **Offset_Policy**: 将平仓需求拆分为平今与平昨腿的决策逻辑,依据交易所规则与费率高低选择。
- **Reconciliation**: 将本地记录的持仓、资金、委托与期货公司返回结果比对的过程。
- **Halt_State**: 系统禁止提交新开仓委托、等待人工放行的状态。进入该状态不阻止平仓与撤单。
- **Rate_Limiter**: 对 CTP 各类请求施加频率上限的组件,覆盖查询、报单、撤单三类。
- **Compliance_Preflight**: 启动时对穿透式监管所需条件(AppID、AuthCode、采集库)的前置校验。
- **Expiry_Policy**: 合约临近到期时的强制平仓或换月规则。
- **Clock**: 可注入的时间源抽象。所有子系统通过 Clock 获取当前时间,不直接调用系统时钟,以便确定性测试。
- **Log_Service**: 记录系统运行日志的子系统。
- **Alert_Service**: 对异常事件发出告警的子系统。
- **Config_Manager**: 加载、校验、保存配置的子系统。
- **Tick**: 由 CTP 推送的单条行情快照,国内期货推送间隔约 500ms。Tick 为周期性状态快照,非逐笔成交,单个快照周期内发生的多笔成交被合并。
- **Bar**: 1 分钟周期 K 线,包含时间戳、开高低收、成交量、成交额、持仓量。**Bar 的时间戳定义为该分钟的起始时刻**,即时间戳 09:01 的 Bar 覆盖 09:01:00 至 09:01:59.999 的行情。
- **Canonical_Symbol**: 合约的系统内唯一规范写法,格式为品种代码加 4 位年月加交易所后缀,例如 `rb2510.SHFE`。所有模块内部一律使用该形式,与外部接口的写法转换仅在指定的单一转换点发生。
- **Trading_Day**: 交易日,由时间戳经统一映射函数得出。夜盘时段归属其后的交易日,与自然日不同。
- **Client_Order_Id**: 系统为每笔委托意图生成的幂等键,格式包含交易日、品种与序号,在进程重启后保持稳定,用于断线后判定委托是否已送达。
- **Golden_Fixture**: 冻结不变的测试数据集,覆盖夜盘跨日、周五夜盘、节前夜盘停盘、郑商所 3 位年月码、主力换月、涨跌停封板、零成交分钟等已知边界场景。
- **Tick_Whitelist**: 需要落库 tick 数据的合约代码配置清单。
- **Recording_Whitelist**: 需要落库 1 分钟 K 线的合约范围配置,默认值为全市场。
- **SimNow**: 上期技术提供的 CTP 模拟交易环境,用于开发与调试。
- **Trading_Session**: 一个连续的可交易时间区间,例如日盘 09:00–10:15 或夜盘 21:00–23:00。
- **Module_Package**: 一个独立子文件夹形式的代码模块,包含显式的对外接口定义文件。
- **Credential**: 期货账户的账号、密码、经纪商代码等敏感信息。

## Requirements

### Requirement 1: CTP 行情接入

**User Story:** 作为个人交易者,我希望系统通过期货公司 CTP 接口接收实时行情,以便获得免费且低延迟的市场数据来源。

#### Acceptance Criteria

1. WHEN Recorder_Process 或 Live_Process 启动,THE Compliance_Preflight SHALL 在建立 CTP 连接之前校验穿透式监管所需的 AppID 与 AuthCode 配置项非空、且穿透式监管采集库文件在本机存在
2. IF Compliance_Preflight 的任一校验项未通过,THEN THE Trading_System SHALL 终止启动流程并输出包含未通过项名称的错误信息,不发起 CTP 连接
3. WHEN Compliance_Preflight 全部校验通过,THE Log_Service SHALL 记录已解析的 AppID 与采集库路径,且不记录 Credential 中的密码字段
4. WHEN 进程启动流程进入连接阶段,THE Market_Data_Gateway SHALL 使用 Config_Manager 提供的 Credential 建立 CTP 行情连接与交易连接
5. WHEN CTP 行情连接建立成功,THE Market_Data_Gateway SHALL 向 EventEngine 发布连接成功事件并由 Log_Service 记录连接成功日志
6. IF CTP 登录返回错误码,THEN THE Market_Data_Gateway SHALL 记录包含错误码与错误描述的日志,并向 Alert_Service 发布登录失败事件
7. IF CTP 连接在运行期间中断,THEN THE Market_Data_Gateway SHALL 按配置的重连间隔(默认 10 秒)发起重连,重连尝试次数上限默认为 30 次
8. IF 重连尝试次数达到配置上限,THEN THE Market_Data_Gateway SHALL 停止重连并向 Alert_Service 发布连接失败告警事件
9. WHERE 配置项 `environment` 取值为 `simnow`,THE Market_Data_Gateway SHALL 连接 SimNow 模拟环境的服务器地址
10. WHEN Market_Data_Gateway 接收到一条 Tick,THE Market_Data_Gateway SHALL 将该 Tick 转换为系统内部 Tick 结构并通过 EventEngine 发布行情事件
11. THE Market_Data_Gateway SHALL 在向 CTP 提交任何请求之前经由 Rate_Limiter 取得许可
12. THE Rate_Limiter SHALL 对查询类请求施加每秒 1 次的频率上限,该上限由配置项 `gateway.max_queries_per_second` 控制
13. THE Rate_Limiter SHALL 对报单请求与撤单请求分别施加独立的频率上限
14. IF Rate_Limiter 判定某请求超出频率上限,THEN THE Market_Data_Gateway SHALL 延迟该请求至下一个可用时隙而非丢弃该请求
15. THE Trading_System SHALL 使全部 CTP 请求经由 Rate_Limiter,不在 Market_Data_Gateway 之外的模块直接调用 CTP 接口
16. WHEN CTP 交易连接登录成功,THE Market_Data_Gateway SHALL 执行合约查询一次,且不在同一会话内重复执行该查询

### Requirement 2: 合约订阅管理

**User Story:** 作为个人交易者,我希望集中管理订阅合约清单,以便控制行情流量并保证策略所需合约均已订阅。

#### Acceptance Criteria

1. THE Subscription_Manager SHALL 从配置文件读取订阅合约清单,清单条目支持具体合约代码与品种代码两种形式
2. WHEN CTP 合约查询完成,THE Subscription_Manager SHALL 将品种代码形式的清单条目展开为该品种当前所有在交易所挂牌的合约代码
3. WHEN 订阅合约清单展开完成,THE Subscription_Manager SHALL 对清单内每个合约代码调用 Market_Data_Gateway 的订阅接口
4. IF 清单中的某个合约代码在 CTP 合约查询结果中不存在,THEN THE Subscription_Manager SHALL 跳过该合约并记录包含该合约代码的警告日志
5. WHEN 用户提交新增订阅指令,THE Subscription_Manager SHALL 在不重启 Recorder_Process 的前提下完成该合约订阅
6. THE Subscription_Manager SHALL 将 CTP 合约查询返回的组合合约与跨期套利合约代码识别出来并排除在订阅清单之外
7. WHEN Subscription_Manager 展开品种代码形式的清单条目,THE Subscription_Manager SHALL 将展开结果中的每个合约代码转换为 Canonical_Symbol
8. THE Subscription_Manager SHALL 提供查询接口,返回当前已成功订阅的合约代码集合

### Requirement 3: 交易时段识别

**User Story:** 作为个人交易者,我希望系统准确识别包含夜盘的交易时段,以便在非交易时间不产生无效数据与无效委托。

#### Acceptance Criteria

1. THE Trading_Session_Calendar SHALL 经 `meta` Module_Package 的 Reference_Data_Store 端口读取每个品种的 Trading_Session 定义,定义内容包含日盘区间、夜盘区间与该定义的生效日期区间;不得为此依赖更高层级的 `data` Module_Package
2. THE Trading_Session_Calendar SHALL 使 Trading_Session 定义按品种与生效日期版本化存储,同一品种在不同历史时期可具有不同的时段定义
3. WHEN 外部调用方传入品种代码与参考日期,THE Trading_Session_Calendar SHALL 返回该品种在该日期生效的 Trading_Session 定义
4. THE Trading_Session_Calendar SHALL 提供**唯一一个**由时间戳映射到 Trading_Day 的函数,Trading_System 内全部子系统的交易日判定均通过该函数完成
5. WHERE 时间戳落在夜盘区间内,THE Trading_Session_Calendar SHALL 将该时间戳的 Trading_Day 判定为其后的第一个交易日
6. WHERE 时间戳落在周五夜盘区间内,THE Trading_Session_Calendar SHALL 将该时间戳的 Trading_Day 判定为下一周的第一个交易日
7. WHERE 某交易日的次日为节假日且该品种夜盘按交易所公告停盘,THE Trading_Session_Calendar SHALL 判定该夜盘时段不存在,而非将其顺延至节后
8. WHEN 外部调用方传入合约代码与时间戳,THE Trading_Session_Calendar SHALL 返回该时间戳是否落在该合约的 Trading_Session 内的布尔判定结果
9. WHEN 外部调用方传入自然日日期,THE Trading_Session_Calendar SHALL 返回该日期是否为交易日的判定结果
10. IF 接收到的 Tick 时间戳不落在该合约的任一 Trading_Session 内,THEN THE Tick_Recorder SHALL 丢弃该 Tick 并记录一条计数型警告日志
11. THE Trading_Session_Calendar SHALL 提供接口返回指定合约在指定交易日内应存在的 1 分钟 Bar 数量
12. THE Trading_Session_Calendar SHALL 提供接口返回指定品种的集合竞价时段区间
13. IF 请求判定的日期在交易日历数据覆盖范围之外,THEN THE Trading_Session_Calendar SHALL 抛出错误而非返回推测结果
14. THE Trading_Session_Calendar SHALL 通过 Clock 获取当前时间,不直接调用系统时钟

### Requirement 4: Tick 数据落库

**User Story:** 作为个人交易者,我希望仅对配置清单内的合约落库 tick 数据,以便在单机存储容量范围内为未来订单流研究积累原始数据。

#### Acceptance Criteria

1. THE Tick_Recorder SHALL 从配置文件读取 Tick_Whitelist,并仅对 Tick_Whitelist 内的合约执行 tick 落库
2. WHEN Tick_Recorder 接收到 Tick_Whitelist 内合约的一条 Tick,THE Tick_Recorder SHALL 通过 Data_Store 接口将该 Tick 持久化
3. WHEN Tick_Recorder 接收到 Tick_Whitelist 之外合约的一条 Tick,THE Tick_Recorder SHALL 丢弃该 Tick 且不执行任何数据库写入
4. THE Tick_Recorder SHALL 以批量方式写入 tick 数据,批量大小与最长驻留时间由配置项控制,默认值分别为 500 条与 3 秒
5. WHEN 用户在配置文件中向 Tick_Whitelist 增加合约代码并重新加载配置,THE Tick_Recorder SHALL 在不修改任何代码文件的前提下开始落库该合约的 tick 数据
6. IF Data_Store 的 tick 写入调用抛出异常,THEN THE Tick_Recorder SHALL 记录包含合约代码与异常信息的错误日志,保留内存中未写入的数据并在下一个批量周期重试
7. IF 同一批数据的连续重试次数达到配置项 `storage.max_write_retries`(默认 3 次),THEN THE Tick_Recorder SHALL 将该批数据写入本地兜底文件、清空内存缓冲、并向 Alert_Service 发布写入失败事件
8. THE Tick_Recorder SHALL 使内存缓冲的驻留记录数上限由配置项 `storage.max_buffer_records`(默认 100000 条)控制,达到上限时执行兜底文件落盘
9. THE Trading_System SHALL 提供将兜底文件中的记录重新写入 Data_Store 的重放接口
10. THE Tick_Recorder SHALL 直接注册 Market_Data_Gateway 的行情回调获取 Tick,不经由承载 Monitor_Shell 的 EventEngine 队列
11. WHILE Trading_System 处于运行状态,THE Tick_Recorder SHALL 提供当日已落库 tick 条数的统计查询接口

### Requirement 5: 1 分钟 K 线合成

**User Story:** 作为个人交易者,我希望系统将 CTP 快照聚合为全市场 1 分钟 K 线并落库,以便建立自有的分钟级历史数据资产。

#### Acceptance Criteria

1. THE Bar_Aggregator SHALL 从配置文件读取 Recording_Whitelist,Recording_Whitelist 默认值为已订阅的全部合约
2. THE Bar_Aggregator SHALL 将 Bar 的时间戳取值为该 Bar 所覆盖分钟的**起始时刻**
3. THE Bar_Aggregator SHALL 为每个 Bar 记录经 Trading_Session_Calendar 映射得出的 Trading_Day,该取值对夜盘 Bar 与其所属交易日一致
4. WHEN Bar_Aggregator 接收到一条 Tick,THE Bar_Aggregator SHALL 用该 Tick 的最新价更新对应合约当前 1 分钟 Bar 的最高价、最低价与收盘价
5. WHEN 某合约收到时间戳分钟数大于当前 Bar 分钟数的 Tick,THE Bar_Aggregator SHALL 将当前 Bar 标记为完成并通过 EventEngine 发布 Bar 完成事件
6. WHEN Bar_Aggregator 发布 Bar 完成事件,THE Bar_Aggregator SHALL 在该事件发布后 5 秒内通过 Data_Store 接口完成该 Bar 的持久化
7. THE Bar_Aggregator SHALL 将 Bar 的成交量计算为该分钟内最后一条 Tick 的累计成交量减去上一个 Bar 最后一条 Tick 的累计成交量
8. THE Bar_Aggregator SHALL 将 Bar 的持仓量取值为该分钟内最后一条 Tick 的持仓量字段值
9. WHEN 某合约的一个 Trading_Session 结束,THE Bar_Aggregator SHALL 强制完成该合约当前未完成的 Bar 并执行持久化
10. IF 某合约在一个完整分钟内未收到任何 Tick,THEN THE Bar_Aggregator SHALL 不为该分钟生成 Bar 记录
11. THE Bar_Aggregator SHALL 将集合竞价时段产生的行情排除在 Bar 序列之外,并对每个 Trading_Session 的首个 Bar 附加开盘标记
12. FOR ALL 由 Bar_Aggregator 生成的 Bar,该 Bar 的时间戳 SHALL 落在 Trading_Session_Calendar 为该合约该 Trading_Day 定义的某个 Trading_Session 区间内

### Requirement 6: 数据库访问抽象

**User Story:** 作为个人交易者,我希望市场数据访问经过稳定的存储端口,以便替换 Parquet/DuckDB 的具体实现时不修改业务代码,同时不把运行状态与告警记录混入市场数据所有权。

#### Acceptance Criteria

1. THE Data_Store SHALL 提供实现 vn.py `BaseDatabase` 协议的适配层,使 Backtest_Engine 能够不加修改地从本系统存储读取 Bar 与 tick
2. THE Data_Store SHALL 提供自有持久化接口,承载 `BaseDatabase` 协议未覆盖的市场数据集:质量检测结果、异常标记集、Provenance_Table 与 Ingest_Manifest;策略参数与内部变量由 Runtime_State_Store 持有,告警记录由 Alert_Service 追加至事件流文件
3. THE Trading_System SHALL 使每类持久化细节由其状态所有者封装:市场数据 SQL 与路径拼接仅在 data Module_Package,参考事实仅在 meta,运行状态仅在 runtime,日志与事件流仅在 obs;各模块的调用方只依赖公开端口,不包含对应存储的 SQL 语句文本与路径拼接
4. WHEN 替换 Data_Store 的 Parquet/DuckDB 具体实现,THE Trading_System SHALL 通过组合根注入新的存储端口实现,且不修改 Data_Store 之外的业务逻辑源码;存储后端不是允许运行期热切换的配置项
5. THE Data_Store SHALL 提供按合约代码、交易所、周期、时间区间查询 Bar 序列的接口
6. THE Data_Store SHALL 提供按合约代码、交易所、时间区间查询 tick 序列的接口
7. THE Data_Store SHALL 将数据划分为 Raw_Layer 与 Curated_Layer,并使 Curated_Layer 的全部内容可由 Raw_Layer 重新构建
8. THE Data_Store SHALL 使 Raw_Layer 的写入操作仅为追加,不提供针对 Raw_Layer 已有记录的修改接口与删除接口
9. WHEN 对 Curated_Layer 的某个分区执行构建,THE Data_Store SHALL 整体重写该分区而非追加记录
10. THE Data_Store SHALL 为 Curated_Layer 的每次构建产生 Data_Version 标识并记入 Ingest_Manifest
11. THE Data_Store SHALL 在写入每条 Bar 记录时向 Provenance_Table 记录该记录的数据来源与写入时间
12. THE Data_Store SHALL 在数据文件元信息中记录 schema 版本号
13. FOR ALL 合法的 Bar 记录,经 Data_Store 写入后再按相同键读取,读取结果的全部字段值 SHALL 与写入值相等(round-trip 属性)
14. FOR ALL 合法的 tick 记录,经 Data_Store 写入后再按相同键读取,读取结果的全部字段值 SHALL 与写入值相等(round-trip 属性)
15. WHEN 写入 Curated_Layer 的 Bar 记录与已存在记录的合约代码、交易所、周期、时间戳完全相同,THE Data_Store SHALL 依据 Provenance_Table 的来源优先级决定取舍,且该键的记录数保持为 1
16. WHEN Backtest_Engine 或研究程序访问 Data_Store,THE Data_Store SHALL 以只读方式建立连接
17. IF Recorder_Process 正在运行且 Curated_Layer 构建任务被提交,THEN THE Data_Store SHALL 拒绝该构建任务并输出提示信息

### Requirement 7: 数据缺失检测

**User Story:** 作为个人交易者,我希望系统自动发现历史数据缺失,以便在回测前确认数据完整性。

#### Acceptance Criteria

1. WHEN 用户提交缺失检测指令并指定合约代码与日期区间,THE Data_Quality_Checker SHALL 输出该区间内每个交易日的实际 Bar 数量与 Trading_Session_Calendar 给出的应有 Bar 数量的差值
2. THE Data_Quality_Checker SHALL 区分**真实缺失**与**无成交**两种 Bar 缺口:某分钟无 Bar 且同品种当日主力合约在该分钟存在 Bar 时判定为真实缺失,同品种主力合约在该分钟同样无 Bar 时判定为无成交
3. IF 某交易日存在真实缺失的 Bar,THEN THE Data_Quality_Checker SHALL 输出该交易日真实缺失 Bar 的时间戳清单
4. THE Data_Quality_Checker SHALL 使无成交类缺口不触发 Alert_Service 事件,仅计入检测报告的统计计数
5. IF 某合约在某交易日的实际 Bar 数量为 0 且该交易日为该合约挂牌期内的交易日,THEN THE Data_Quality_Checker SHALL 将该交易日标记为整日缺失
6. WHEN 每个交易日的日盘与夜盘全部结束,THE Data_Quality_Checker SHALL 对 Recording_Whitelist 内全部合约执行当日缺失检测
7. IF 当日缺失检测发现真实缺失的 Bar,THEN THE Data_Quality_Checker SHALL 向 Alert_Service 发布数据缺失事件,事件内容包含合约代码与真实缺失时间戳数量
8. THE Data_Quality_Checker SHALL 将每次检测结果以结构化记录形式通过 Data_Store 自有接口持久化
9. WHEN 用户提交缺口查询指令,THE Data_Quality_Checker SHALL 输出按合约与日期区间聚合的真实缺失汇总表,用于判定哪些回测区间的数据完整性不足

### Requirement 8: 数据异常值检测

**User Story:** 作为个人交易者,我希望系统识别跳价、零成交与时间戳错乱等异常数据,以便避免污染回测结果。

#### Acceptance Criteria

1. WHEN Data_Quality_Checker 检测某合约的 Bar 序列,THE Data_Quality_Checker SHALL 将相邻 Bar 收盘价变动幅度超过配置阈值(默认为该品种当日涨跌停幅度)的 Bar 标记为跳价异常
2. WHEN Data_Quality_Checker 检测某合约的 Bar 序列,THE Data_Quality_Checker SHALL 将成交量为 0 且最高价与最低价不相等的 Bar 标记为零成交异常
3. WHEN Data_Quality_Checker 检测某合约的 Bar 序列,THE Data_Quality_Checker SHALL 将时间戳小于或等于前一条记录时间戳的 Bar 标记为时间戳错乱异常
4. THE Data_Quality_Checker SHALL 将最高价小于最低价、开盘价超出最高价与最低价区间、收盘价超出最高价与最低价区间的 Bar 标记为价格区间异常
5. THE Data_Quality_Checker SHALL 将价格取值不为该合约最小变动价位整数倍的 Bar 标记为价格精度异常
6. THE Data_Quality_Checker SHALL 将价格超出交易所公布的当日涨跌停价格区间的 Bar 标记为越界异常
7. WHEN 交易所日行情文件可用,THE Data_Quality_Checker SHALL 将该交易日最后一个 Bar 的收盘价与交易所公布收盘价比对,差值超过 1 个最小变动价位时标记为收盘价不一致异常
8. THE Data_Quality_Checker SHALL 为每类异常赋予严重级别,取值为 ERROR 或 WARNING
9. WHEN 异常值检测完成,THE Data_Quality_Checker SHALL 输出包含合约代码、时间戳、异常类型、严重级别、异常字段值的检测报告
10. THE Data_Quality_Checker SHALL 保留被标记为异常的原始记录,并将标记结果通过 Data_Store 自有接口记录在独立的质量标记数据集中
11. IF 某 Curated_Layer 分区的检测结果包含 ERROR 级别异常,THEN THE Data_Store SHALL 拒绝将该分区发布为可用数据,除非构建指令显式携带 `--allow-dirty` 参数
12. WHEN 构建指令携带 `--allow-dirty` 参数并覆盖发布闸门,THE Data_Quality_Checker SHALL 将该次覆盖操作记入质量标记数据集

### Requirement 9: 历史数据回补

**User Story:** 作为个人交易者,我希望系统能自动与手动回补缺失的历史数据,以便持续维护完整的本地数据资产。

#### Acceptance Criteria

1. WHEN 用户提交手动回补指令并指定合约代码、日期区间与数据源,THE Backfill_Service SHALL 通过对应的 History_Import_Adapter 获取该区间 1 分钟 Bar 并通过 Data_Store 接口写入
2. WHEN Data_Quality_Checker 发布数据缺失事件且配置项 `backfill.auto_enabled` 取值为 `true`,THE Backfill_Service SHALL 对缺失时间区间自动执行回补
3. THE Backfill_Service SHALL 按配置项 `backfill.source_priority` 定义的顺序依次尝试数据源,默认顺序为 TQSDK 优先于 akshare
4. IF 优先级较高的数据源返回空结果或抛出异常,THEN THE Backfill_Service SHALL 尝试下一个数据源并记录该次失败的数据源名称
5. IF 全部配置数据源均未返回目标区间数据,THEN THE Backfill_Service SHALL 记录回补失败日志并向 Alert_Service 发布回补失败事件
6. WHEN History_Import_Adapter 返回数据,THE Backfill_Service SHALL 先将原始返回内容写入 Raw_Layer 并登记 Ingest_Manifest,再由 Raw_Layer 构建 Curated_Layer
7. WHEN 回补数据与本地已存在 Bar 的时间戳重复,THE Backfill_Service SHALL 查询 Provenance_Table,保留自建通道落库的记录并丢弃外部数据源的重复记录
8. THE Backfill_Service SHALL 为每条由外部数据源写入的 Bar 在 Provenance_Table 中登记其数据源名称
9. WHEN 回补执行完成,THE Backfill_Service SHALL 对回补区间重新执行缺失检测并输出回补后的真实缺失 Bar 数量
10. FOR ALL 已完成回补的时间区间,重复执行同一条回补指令 SHALL 使 Curated_Layer 中该区间的 Bar 记录集合保持不变(幂等属性)
11. WHEN 同一采集键被重复采集且指令携带强制参数,THE Backfill_Service SHALL 在 Raw_Layer 写入新记录并将原记录标记为已被取代,而非覆盖原记录

### Requirement 10: 外部历史数据导入

**User Story:** 作为个人交易者,我希望通过统一接口接入 TQSDK 与 akshare 等免费历史数据源,以便在不依赖收费数据服务的前提下补齐历史数据。

#### Acceptance Criteria

1. THE History_Import_Adapter SHALL 定义统一导入接口,接口入参为 Canonical_Symbol、周期、起始时间、结束时间,返回值为系统内部 Bar 序列
2. THE Trading_System SHALL 提供 TQSDK 与 akshare 两个 History_Import_Adapter 实现
3. WHEN 新增一个外部数据源实现该统一导入接口,THE Backfill_Service SHALL 在不修改 Backfill_Service 源码的前提下通过配置启用该数据源
4. WHEN History_Import_Adapter 从外部数据源取得数据,THE History_Import_Adapter SHALL 先将原始返回内容原样写入 Raw_Layer,再执行字段映射
5. WHEN History_Import_Adapter 执行字段映射,THE History_Import_Adapter SHALL 将外部数据源的合约代码转换为 Canonical_Symbol
6. THE History_Import_Adapter SHALL 判定外部数据源的 Bar 时间戳约定为分钟起始或分钟结束,并将分钟结束约定的时间戳转换为分钟起始约定
7. FOR ALL 由 History_Import_Adapter 导入的 Bar,该 Bar 的时间戳 SHALL 落在 Trading_Session_Calendar 为该合约该 Trading_Day 定义的某个 Trading_Session 区间内,该断言失败时导入终止并输出错误
8. IF 外部数据源返回记录缺少开高低收或成交量中的任一字段,THEN THE History_Import_Adapter SHALL 丢弃该条记录并记录包含时间戳的警告日志
9. THE History_Import_Adapter SHALL 将外部数据源返回的时间戳统一转换为配置项 `timezone` 指定的时区,默认取值为 `Asia/Shanghai`
10. WHERE 外部数据源对请求频率设定上限,THE History_Import_Adapter SHALL 按配置的请求间隔限制调用速率,默认请求间隔为 1 秒
11. THE Trading_System SHALL 提供 Bar 序列导出为 CSV 文件的接口与从 CSV 文件导入 Bar 序列的接口,导入接口支持券商行情软件导出的 CSV 格式
12. FOR ALL 合法的 Bar 序列,执行导出 CSV 再导入的操作后,得到的 Bar 序列 SHALL 与原序列在全部字段上相等(round-trip 属性)

### Requirement 11: 策略开发框架

**User Story:** 作为个人交易者,我希望策略代码与框架解耦,以便新增或修改策略时只改动策略文件本身。

#### Acceptance Criteria

1. THE Strategy_Framework SHALL 要求每个 Strategy 继承系统自有的策略基类并实现 `on_bar` 方法,`on_start`、`on_stop`、`on_trading_day_start`、`on_fill` 为可选实现
2. THE Trading_System SHALL 使 Strategy 源码的导入依赖仅限于系统自有数据结构模块、指标模块、策略基类模块与 numpy,不包含任何交易框架的导入语句
3. THE Strategy_Framework SHALL 通过 Strategy_Context 协议向 Strategy 提供当前时间、当前 Trading_Day、行情序列、持仓查询与 Target_Position 设置能力
4. THE Strategy_Framework SHALL 要求 Strategy 通过设置 Target_Position 表达交易意图,不要求且不允许 Strategy 直接指定开平标志与委托价格
5. WHERE Strategy 需要使用挂单或停止单,THE Strategy_Framework SHALL 提供直接报单的逃逸接口,并要求该 Strategy 将自身标记为不可向量化
6. THE Strategy_Framework SHALL 使 Strategy 通过 Strategy_Context 获取当前时间,不直接调用系统时钟
7. THE Trading_System SHALL 提供 Engine_Adapter 将 Strategy 适配到具体引擎,并使 Engine_Adapter 是系统内唯一同时依赖交易框架与 Strategy 的代码位置
8. THE Trading_System SHALL 使同一 Strategy 源文件在单品种 Backtest_Engine、多品种 Backtest_Engine 与 Live_Trading_Engine 三种环境下运行时无需修改
9. WHEN 更换 Backtest_Engine 实现,THE Trading_System SHALL 在不修改任何 Strategy 源文件的前提下完成更换
10. THE Strategy_Framework SHALL 使 `on_bar` 的入参为合约代码到 Bar 的映射,以支持单品种与多品种两种场景
11. THE Strategy_Framework SHALL 将传入 `on_bar` 的 Bar 对象声明为临时对象,并提供严格模式使 Bar 对象为不可变副本以便检出违规持有引用的 Strategy
12. WHEN 用户将策略文件放入配置项 `strategy.path` 指定目录并触发策略加载,THE Strategy_Framework SHALL 在不修改 Strategy_Framework 源码的前提下加载该 Strategy 类
13. THE Strategy_Framework SHALL 通过 Strategy 类的参数声明列表暴露可配置参数及其默认值
14. WHEN 用户为同一 Strategy 类创建多个实例并分别指定实例名称与合约代码,THE Strategy_Framework SHALL 使各实例的参数与运行状态相互独立
15. IF 某 Strategy 实例的回调方法抛出异常,THEN THE Strategy_Framework SHALL 停止该实例、记录含堆栈信息的错误日志,并使其他实例继续运行
16. WHEN Strategy 实例启动,THE Engine_Adapter SHALL 通过 `data` Module_Package 的公开 Data_Store 端口加载该 Strategy 声明的预热 Bar 数量并注入行情序列,默认取值为 100;Strategy 与 Strategy_Framework 不直接依赖 Data_Store
17. THE Strategy_Framework SHALL 以行情序列已完成预热的状态标志作为首次触发 `on_bar` 的判定依据,不以已加载 Bar 的计数作为判定依据
18. THE Strategy_Framework SHALL 要求 Strategy 通过状态导出接口返回可 JSON 序列化的内部变量,并使该导出内容携带 schema 版本号
19. THE Trading_System SHALL 为将来接入外部信号来源预留 Strategy 层接口,使基于预测模型的信号可作为 Strategy 的输入而无需改动 Engine_Adapter 与执行链路

### Requirement 12: 回测撮合

**User Story:** 作为个人交易者,我希望按 1 分钟 K 线执行回测并建模滑点与手续费,以便获得接近实盘的收益评估。

#### Acceptance Criteria

1. WHEN 用户提交回测指令并指定策略实例、合约代码、日期区间、初始资金,THE Backtest_Engine SHALL 从 Data_Store 加载该区间 1 分钟 Bar 并按时间顺序驱动策略
2. THE Backtest_Engine SHALL 按每根 Bar 的最高价与最低价判定限价委托是否成交,买入委托的成交价取委托价格与该 Bar 开盘价中的较低者、卖出委托的成交价取委托价格与该 Bar 开盘价中的较高者
3. THE Backtest_Engine SHALL 将买入市价委托的成交价计算为下一根 Bar 开盘价加上滑点、卖出市价委托的成交价计算为下一根 Bar 开盘价减去滑点,滑点数值由配置项 `backtest.slippage` 指定,默认取值为该品种 1 个最小变动价位
4. IF 某根 Bar 的价格触及交易所公布的当日涨跌停价格,THEN THE Backtest_Engine SHALL 判定该方向的委托在该 Bar 不成交
5. THE Backtest_Engine SHALL 通过 Cost_Model 计算每笔成交的手续费并从账户资金中扣除,不使用引擎内置的按成交金额比例计费机制
6. THE Backtest_Engine SHALL 将传入 Cost_Model 的开平标志取值为 Offset_Policy 解析后的结果,使平今与平昨的费率差异在回测中生效
7. THE Backtest_Engine SHALL 通过 Cost_Model 计算持仓占用保证金,保证金率经 `meta` Module_Package 的 Reference_Data_Store 取得该合约在对应交易日生效的版本
8. THE Backtest_Engine SHALL 按每个交易日的 Settlement_Price 计算持仓盯市盈亏与保证金占用
9. IF 某交易日的 Settlement_Price 在 Reference_Data_Store 中不存在,THEN THE Backtest_Engine SHALL 以该交易日最后一根 Bar 的收盘价替代并在回测结果中记录该替代的发生次数
10. WHEN 回测区间内发生 Roll_Event,THE Backtest_Engine SHALL 对换出与换入两腿分别计算手续费,并按配置项 `backtest.roll_slippage_ticks`(默认 2 个最小变动价位)计算换月滑点成本
11. IF 回测所需日期区间内存在真实缺失 Bar,THEN THE Backtest_Engine SHALL 在回测结果中输出真实缺失 Bar 数量并继续执行回测
12. IF 委托数量小于 1 手或不为整数,THEN THE Backtest_Engine SHALL 拒绝该委托并记录拒单原因
13. WHEN 回测执行完成,THE Backtest_Engine SHALL 输出逐笔成交记录、逐日资金曲线、持仓变动记录、手续费合计与换月成本合计
14. WHEN 回测执行完成,THE Backtest_Engine SHALL 在回测结果中记录所用数据的 Data_Version、Roll_Map 规则与 Adjustment_Method
15. WHEN 用户提交回测指令并指定手续费敏感性系数,THE Backtest_Engine SHALL 按该系数放大 Cost_Model 的手续费输出并输出对应的绩效指标
16. FOR ALL 相同的策略参数、日期区间、配置输入与 Data_Version,重复执行回测 SHALL 得到完全相同的成交记录与资金曲线(确定性属性)

### Requirement 13: 多品种组合回测

**User Story:** 作为个人交易者,我希望在同一账户资金下同时回测多个品种,以便评估组合层面的风险与收益。

#### Acceptance Criteria

1. WHEN 用户提交组合回测指令并指定多个合约代码及各自策略实例,THE Backtest_Engine SHALL 将全部合约的 Bar 按时间戳合并为单一有序事件序列并驱动各策略实例
2. THE Trading_System SHALL 通过 Engine_Adapter 使同一 Strategy 源文件既可运行于单品种回测引擎,也可运行于多品种回测引擎
3. THE Trading_System SHALL 在实施前对候选多品种回测引擎执行验证,验证内容包含合约乘数、保证金占用与手续费计算的正确性,并以验证结果确定所采用的引擎
4. THE Backtest_Engine SHALL 使组合回测中的全部策略实例共享同一个账户资金与同一份可用资金余额
5. WHEN 同一时间戳存在多个合约的 Bar,THE Backtest_Engine SHALL 按配置项 `backtest.symbol_order` 定义的固定顺序处理各合约 Bar
6. WHEN 组合回测执行完成,THE Backtest_Engine SHALL 分别输出每个合约的绩效指标与组合整体的绩效指标
7. IF 某合约在组合回测区间内无任何 Bar 数据,THEN THE Backtest_Engine SHALL 记录该合约无数据的警告日志并继续执行其余合约的回测
8. THE Backtest_Engine SHALL 在组合回测中按合约乘数与该合约在对应交易日生效的保证金率分别计算各合约的保证金占用,并按占用合计校验可用资金

### Requirement 14: 绩效指标计算

**User Story:** 作为个人交易者,我希望获得标准化的绩效指标,以便横向比较不同策略与参数的表现。

#### Acceptance Criteria

1. WHEN 收到逐日资金曲线与成交记录,THE Performance_Analyzer SHALL 计算总收益率、年化收益率、最大回撤、最大回撤持续天数、夏普比率、胜率、盈亏比、总成交笔数、总手续费
2. THE Performance_Analyzer SHALL 按配置项 `performance.annual_days` 指定的年交易日数计算年化指标,默认取值为 240
3. THE Performance_Analyzer SHALL 按配置项 `performance.risk_free_rate` 指定的无风险利率计算夏普比率,默认取值为 0
4. THE Performance_Analyzer SHALL 将最大回撤定义为资金曲线从历史最高点到后续最低点的最大跌幅百分比
5. THE Performance_Analyzer SHALL 将胜率定义为盈利平仓交易笔数除以总平仓交易笔数
6. THE Performance_Analyzer SHALL 将盈亏比定义为盈利平仓交易的平均盈利金额除以亏损平仓交易的平均亏损金额绝对值
7. IF 总平仓交易笔数为 0,THEN THE Performance_Analyzer SHALL 将胜率与盈亏比输出为空值并输出零交易提示
8. IF 逐日收益标准差为 0,THEN THE Performance_Analyzer SHALL 将夏普比率输出为空值
9. THE Performance_Analyzer SHALL 按 Settlement_Price 计算逐日浮动盈亏,不以收盘价替代 Settlement_Price
10. WHEN 输出绩效报告,THE Performance_Analyzer SHALL 一并输出所用数据的 Data_Version、Roll_Map 规则与 Adjustment_Method
11. THE Performance_Analyzer SHALL 使账户权益变化量等于已实现盈亏与浮动盈亏之和减去手续费合计、滑点成本合计与换月成本合计(资金守恒属性)

### Requirement 15: 参数优化

**User Story:** 作为个人交易者,我希望对策略参数执行批量搜索,以便找到绩效表现较优的参数组合。

#### Acceptance Criteria

1. WHEN 用户提交参数优化指令并指定各参数的取值范围与步长,THE Parameter_Optimizer SHALL 生成全部参数组合并对每个组合执行一次回测
2. THE Parameter_Optimizer SHALL 按用户指定的目标指标对全部参数组合的回测结果排序并输出排序后的结果列表
3. THE Parameter_Optimizer SHALL 支持穷举搜索与遗传算法搜索两种模式,模式由指令参数 `optimizer.mode` 指定,默认取值为穷举搜索
4. THE Parameter_Optimizer SHALL 按配置项 `optimizer.max_workers` 指定的并行进程数执行回测,默认取值为 CPU 物理核心数减 1,并以独立进程而非线程实现并行
5. IF 某个参数组合的回测执行抛出异常,THEN THE Parameter_Optimizer SHALL 将该组合的目标指标记为空值、记录异常日志并继续执行其余组合
6. IF 参数组合总数超过配置项 `optimizer.max_combinations` 指定上限(默认 10000),THEN THE Parameter_Optimizer SHALL 拒绝执行并输出包含组合总数的提示信息
7. WHEN 参数优化执行完成,THE Parameter_Optimizer SHALL 将全部组合的参数取值与绩效指标导出为 CSV 文件

### Requirement 16: 实盘与模拟盘策略运行

**User Story:** 作为个人交易者,我希望在模拟盘验证后以相同方式运行实盘策略,以便降低上线风险。

#### Acceptance Criteria

1. WHEN 用户对某策略实例提交启动指令,THE Live_Trading_Engine SHALL 加载该实例参数、执行历史数据预热并将该实例状态置为运行中
2. WHILE 某策略实例处于运行中状态,THE Live_Trading_Engine SHALL 在每根 1 分钟 Bar 完成时调用该实例的 `on_bar` 方法
3. WHILE 某策略实例处于运行中状态且 Trading_System 不处于 Halt_State,THE Live_Trading_Engine SHALL 在无人工确认的前提下将该实例设置的 Target_Position 提交至 Order_Manager 执行
4. WHEN 某策略实例设置的 Target_Position 与该合约实际持仓不一致,THE Live_Trading_Engine SHALL 在后续每根 Bar 完成时持续尝试收敛该差额,直至一致或该实例停止
5. WHEN 用户对某策略实例提交停止指令,THE Live_Trading_Engine SHALL 撤销该实例的全部活动委托并将该实例状态置为已停止
6. THE Live_Trading_Engine SHALL 在每次策略实例状态或参数变更时通过 runtime Module_Package 的 Runtime_State_Store 端口持久化该实例的参数、内部变量与状态 schema 版本
7. WHEN Live_Process 重启后加载策略实例,THE Live_Trading_Engine SHALL 恢复上次持久化的参数与内部变量取值
8. IF 持久化的策略状态 schema 版本与当前 Strategy 声明的版本不一致,THEN THE Live_Trading_Engine SHALL 拒绝启动该实例并输出包含两侧版本号的错误信息
9. IF 策略实例发出委托时该实例状态不为运行中,THEN THE Live_Trading_Engine SHALL 拒绝该委托并记录拒单原因
10. THE Live_Trading_Engine SHALL 在同一进程内支持多个策略实例并行运行,实例数量上限由配置项 `live.max_strategies` 指定,默认取值为 20
11. THE Live_Trading_Engine SHALL 在每个 Trading_Session 开始之前完成连接、订阅与 Reconciliation,并在 Trading_Session 结束后按配置的持仓过夜策略执行持仓保留或平仓
12. WHEN 新的 Trading_Day 开始,THE Live_Trading_Engine SHALL 调用各运行中策略实例的交易日起始回调
13. WHERE 配置项 `environment` 取值为 `simnow`,THE Live_Trading_Engine SHALL 在 State_Snapshot 中标记当前为模拟环境
14. THE Live_Trading_Engine SHALL 以 headless 方式运行,不依赖图形界面进程的存在
15. THE Live_Trading_Engine SHALL 使 Strategy 设置的 Target_Position 对应的合约代码为实际可交易合约代码;WHERE 策略以连续合约序列作为行情输入,THE Live_Trading_Engine SHALL 经 Roll_Map 解析出当日实际合约后再提交执行

### Requirement 17: 委托下单与成交管理

**User Story:** 作为个人交易者,我希望完整跟踪每笔委托的生命周期,以便随时确认下单与成交状态。

#### Acceptance Criteria

1. WHEN Live_Trading_Engine 提交 Target_Position 差额,THE Order_Manager SHALL 经 Offset_Policy 解析出开平标志与各腿数量后生成委托请求
2. WHEN Order_Manager 生成委托请求,THE Order_Manager SHALL 为该请求分配 Client_Order_Id 并写入只追加的委托流水
3. WHEN 策略实例发出委托请求,THE Order_Manager SHALL 在提交至 Market_Data_Gateway 前调用 Risk_Manager 执行风控校验
4. WHEN Risk_Manager 返回校验通过,THE Order_Manager SHALL 将委托提交至 CTP 并记录包含策略实例名称、Client_Order_Id、合约代码、方向、开平、价格、数量的委托日志
5. WHEN 接收到 CTP 委托回报,THE Order_Manager SHALL 更新该委托的状态并通过 EventEngine 发布委托状态事件
6. WHEN 接收到 CTP 成交回报,THE Order_Manager SHALL 更新对应委托的累计成交数量并通过 EventEngine 发布成交事件
7. THE Offset_Policy SHALL 将上海期货交易所与上海国际能源交易中心品种的平仓委托按平今与平昨拆分为独立委托腿并分别标记开平标志
8. WHEN 某合约同时存在今仓与昨仓且两者均可用于平仓,THE Offset_Policy SHALL 依据 `meta` Module_Package 的 Reference_Data_Store 返回的该合约当日平今费率与平昨费率选择费用较低的一腿优先平仓
9. IF 平今费率与平昨费率相等,THEN THE Offset_Policy SHALL 优先平昨仓
10. THE Order_Manager SHALL 使限价委托的报价不超出交易所公布的当日涨跌停价格区间
11. IF CTP 返回委托被拒绝,THEN THE Order_Manager SHALL 记录包含拒绝原因文本的错误日志、向 Alert_Service 发布下单失败事件、并将该拒绝结果通知发出该委托的策略实例
12. IF 某委托在配置项 `live.order_timeout_seconds`(默认 60 秒)内处于部分成交状态且未继续成交,THEN THE Order_Manager SHALL 撤销该委托的未成交部分并将实际成交数量通知发出该委托的策略实例
13. WHEN Risk_Manager 否决某委托,THE Order_Manager SHALL 将该否决结果与否决原因通知发出该委托的策略实例
14. WHEN 用户提交撤单指令,THE Order_Manager SHALL 对指定的活动委托发送撤单请求
15. THE Order_Manager SHALL 提供查询接口返回当前全部活动委托,活动委托定义为状态不为全部成交、已撤销、已拒绝的委托
16. WHEN Live_Process 重启,THE Order_Manager SHALL 从委托流水重建各 Client_Order_Id 的最后已知状态
17. THE Order_Manager SHALL 使每笔委托的累计成交数量始终小于或等于该委托的委托数量(不变式)
18. FOR ALL 提交至 CTP 的委托,该委托的 Client_Order_Id SHALL 在委托流水中唯一(幂等属性)

### Requirement 18: 持仓与资金查询

**User Story:** 作为个人交易者,我希望实时查看持仓与资金,以便掌握账户风险敞口。

#### Acceptance Criteria

1. WHEN CTP 交易连接登录成功,THE Account_Service SHALL 查询账户资金与持仓并通过 EventEngine 发布账户事件与持仓事件
2. THE Account_Service SHALL 按配置项 `account.query_interval` 指定的间隔周期性查询账户资金与持仓,默认取值为 5 秒
3. THE Account_Service SHALL 使全部查询请求经由 Rate_Limiter 取得许可后发出
4. WHEN 接收到成交事件,THE Account_Service SHALL 更新对应合约的本地持仓数量与持仓成本
5. THE Account_Service SHALL 分别维护每个合约的多头持仓数量、空头持仓数量、今仓数量、昨仓数量
6. THE Account_Service SHALL 提供查询接口返回账户权益、可用资金、占用保证金、当日已实现盈亏、当前浮动盈亏
7. THE Trading_System SHALL 以期货公司返回的持仓与资金查询结果作为唯一真相来源,Account_Service 维护的本地记录为其镜像
8. WHEN CTP 连接建立、重连完成或新 Trading_Day 开始,THE Reconciliation SHALL 查询持仓、资金、委托、成交并与本地记录比对
9. THE Reconciliation SHALL 在今仓数量与昨仓数量两个层级分别比对持仓,不仅比对净持仓数量
10. IF Reconciliation 发现任一比对项不一致,THEN THE Trading_System SHALL 进入 Halt_State、向 Alert_Service 发布对账不符事件、并记录包含两侧数值的错误日志
11. THE Trading_System SHALL 不以期货公司返回值自动覆盖本地记录,且不在 Halt_State 下自行退出该状态
12. WHILE Trading_System 处于 Halt_State,THE Order_Manager SHALL 拒绝全部开仓委托并允许平仓委托与撤单请求通过
13. WHEN 用户提交人工放行指令,THE Trading_System SHALL 以期货公司返回值重建本地记录并退出 Halt_State,且记录该次放行操作
14. WHEN Reconciliation 发现本地委托流水中存在状态未确定的 Client_Order_Id,THE Reconciliation SHALL 依据期货公司返回的委托与成交记录判定该委托是否已送达,不以本地缺失回报推断该委托未送达
15. THE Account_Service SHALL 使每个合约的今仓数量与昨仓数量之和等于该合约该方向的总持仓数量(不变式)

### Requirement 19: 交易风控

**User Story:** 作为个人交易者,我希望在下单前执行强制风控校验,以便控制单笔与单日的风险暴露并满足交易所限制。

#### Acceptance Criteria

1. WHEN Risk_Manager 接收到委托校验请求,THE Risk_Manager SHALL 依次执行可用资金校验、总仓位上限校验、单品种持仓上限校验、单日亏损上限校验、下单频率校验、撤单次数校验、涨跌停校验、临近到期校验,并返回校验结论与失败原因
2. THE Risk_Manager SHALL 以委托意图集合、已观测账户状态、风控上限三者为入参,不依赖 Order_Manager 与 Market_Data_Gateway 的内部状态
3. IF 委托预估占用保证金与预估手续费之和大于账户可用资金,THEN THE Risk_Manager SHALL 拒绝该委托并返回可用资金不足原因
4. IF 委托成交后的占用保证金合计与账户权益之比将超过配置项 `risk.max_margin_ratio`(默认 0.5),THEN THE Risk_Manager SHALL 拒绝该委托并返回总仓位超限原因
5. IF 委托成交后该品种持仓手数将超过配置项 `risk.max_position_per_symbol`(默认 10 手),THEN THE Risk_Manager SHALL 拒绝该委托并返回单品种持仓超限原因
6. IF 当日已实现亏损与浮动亏损之和的绝对值达到配置项 `risk.max_daily_loss`(默认为当日开盘账户权益的 3%),THEN THE Risk_Manager SHALL 拒绝全部开仓委托并向 Alert_Service 发布单日亏损触限事件
7. IF 最近 1 秒内已提交的委托笔数达到配置项 `risk.max_orders_per_second`(默认 2 笔),THEN THE Risk_Manager SHALL 拒绝该委托并返回下单频率超限原因
8. IF 某合约当日已提交撤单次数达到配置项 `risk.max_cancels_per_symbol_per_day`(默认 400 次),THEN THE Risk_Manager SHALL 拒绝对该合约的新增撤单请求并返回撤单次数超限原因
9. IF 委托价格超出交易所公布的当日涨跌停价格区间,THEN THE Risk_Manager SHALL 拒绝该委托并返回价格越界原因
10. WHILE 单日亏损上限已触发,THE Risk_Manager SHALL 允许平仓委托通过校验
11. WHILE Trading_System 处于 Halt_State,THE Risk_Manager SHALL 拒绝全部开仓委托并允许平仓委托通过校验
12. THE Risk_Manager SHALL 以账户级 Trading_Day 切换时点作为当日计数重置的唯一触发时点,该时点由 Trading_Session_Calendar 统一给出,不由单个品种的 Trading_Session 开始事件触发
13. WHEN 账户级 Trading_Day 切换时点到达,THE Risk_Manager SHALL 将当日已实现亏损计数、下单笔数计数、各合约撤单次数计数重置为 0
14. THE Risk_Manager SHALL 按配置项 `risk.margin_monitor_interval`(默认 60 秒)周期性核算当前持仓的保证金占用与账户权益之比
15. IF 持仓期间的保证金占用与账户权益之比超过配置项 `risk.max_margin_ratio`,THEN THE Risk_Manager SHALL 向 Alert_Service 发布保证金超限事件
16. WHERE 下一交易日为节假日前最后一个交易日且配置项 `risk.pre_holiday_reduce_enabled` 取值为 `true`,THE Risk_Manager SHALL 按配置项 `risk.pre_holiday_max_position_ratio` 限制持仓上限
17. WHEN Risk_Manager 拒绝一笔委托,THE Risk_Manager SHALL 记录包含策略实例名称、合约代码、拒绝原因的风控日志
18. IF Risk_Manager 自身的校验逻辑抛出异常,THEN THE Trading_System SHALL 进入 Halt_State 并向 Alert_Service 发布风控失效事件,不以校验通过作为异常时的默认结论

### Requirement 20: 日志与运行监控

**User Story:** 作为个人交易者,我希望获得结构化且可追溯的运行日志,以便复盘与排查问题。

#### Acceptance Criteria

1. THE Log_Service SHALL 为每条日志记录时间戳、日志级别、来源模块名称、日志内容,并以结构化格式写入
2. THE Log_Service SHALL 支持 DEBUG、INFO、WARNING、ERROR、CRITICAL 五个日志级别,输出级别由配置项 `log.level` 指定,默认取值为 INFO
3. THE Log_Service SHALL 将日志写入按 Trading_Day 切分的本地日志文件,不以图形界面进程的存在为写入前提
4. THE Log_Service SHALL 按配置项 `log.retention_days` 指定的天数保留本地日志文件,默认取值为 90 天
5. WHEN 本地日志文件保留天数超过配置值,THE Log_Service SHALL 删除超期日志文件并记录删除操作日志
6. THE Recorder_Process 与 Live_Process SHALL 按配置项 `monitor.snapshot_interval` 指定的间隔将运行状态写入 State_Snapshot,默认取值为 1 秒
7. THE State_Snapshot SHALL 包含行情连接状态、交易连接状态、已订阅合约数量、当日落库 Bar 数量、当日落库 tick 数量、各策略实例运行状态、各合约 Target_Position 与实际持仓、当日盈亏、Halt_State 状态、最近心跳时间
8. THE Recorder_Process 与 Live_Process SHALL 以原子替换方式写入 State_Snapshot,使读取方不会读到部分写入的内容
9. IF State_Snapshot 的写入操作抛出异常,THEN THE Recorder_Process 与 Live_Process SHALL 记录该异常并继续执行行情落库与交易逻辑,不因写入失败而中断
10. THE Recorder_Process 与 Live_Process SHALL 将关键事件追加写入本地事件流文件,供 Monitor_Shell 增量读取
11. THE Monitor_Shell SHALL 仅读取 State_Snapshot 与事件流文件,不执行任何写入操作,不建立 CTP 连接
12. WHEN Monitor_Shell 被强制终止,THE Recorder_Process 与 Live_Process SHALL 继续正常运行且不产生数据丢失
13. IF State_Snapshot 的最近心跳时间与当前时间的差值超过配置项 `monitor.heartbeat_timeout`(默认 30 秒),THEN THE Monitor_Shell SHALL 展示进程失联提示
14. THE Trading_System SHALL 按配置项 `monitor.refresh_interval` 指定的间隔刷新监控展示数据,默认取值为 3 秒
15. IF 某已订阅合约在 Trading_Session 内连续超过配置项 `monitor.tick_timeout` 指定时长(默认 60 秒)未收到 Tick 且同品种当日主力合约在同一时段收到了 Tick,THEN THE Trading_System SHALL 向 Alert_Service 发布行情中断事件
16. IF 某已订阅合约与同品种当日主力合约在同一时段均未收到 Tick,THEN THE Trading_System SHALL 不发布该合约的行情中断事件,仅计入统计计数

### Requirement 21: 异常告警

**User Story:** 作为个人交易者,我希望在关键异常发生时立即收到告警,以便及时人工干预。

#### Acceptance Criteria

1. WHEN Alert_Service 接收到告警事件,THE Alert_Service SHALL 记录 ERROR 级别日志,并将一条包含时间戳、告警类型、合约代码、告警内容的记录写入事件流文件,该记录初始状态为未确认
2. THE Alert_Service SHALL 处理连接中断、下单失败、策略异常、数据缺失、行情中断、单日亏损触限、**对账不符、风控失效、穿透式监管校验失败、数据写入失败、保证金超限、到期强制平仓、存储容量告警**十三类告警事件
3. THE Alert_Service SHALL 为每类告警事件标注处置类别,取值为需人工放行、需人工关注、仅记录三者之一
4. WHERE 配置项 `alert.push_url` 取值为非空字符串,THE Alert_Service SHALL 将告警内容以 HTTP POST 请求推送至该地址
5. THE Alert_Service SHALL 对处置类别为需人工放行的告警执行推送,不受告警去重窗口限制
6. IF 告警推送请求返回非成功状态码或超时,THEN THE Alert_Service SHALL 按配置项 `alert.push_retries`(默认 3 次)重试,重试耗尽后记录推送失败日志并使 Trading_System 其余功能继续运行
7. THE Alert_Service SHALL 使告警推送以异步方式执行,不阻塞行情落库与委托提交
8. WHEN 同一类型同一合约的告警在配置项 `alert.dedup_window` 指定时间窗口内重复发生(默认 300 秒),THE Alert_Service SHALL 仅推送首次告警并累加重复计数
9. THE Alert_Service SHALL 在不依赖图形界面进程的前提下完成日志记录与推送
10. THE Alert_Service SHALL 提供查询接口返回当日全部告警记录

### Requirement 22: 配置管理与凭证安全

**User Story:** 作为个人交易者,我希望集中管理配置并保证账号密码不进入版本库,以便安全且可控地调整系统行为。

#### Acceptance Criteria

1. THE Trading_System SHALL 将设定值划分为**市场事实**与**用户选择**两类:随时间变化且存在权威外部来源的取值(手续费率、保证金率、Trading_Session 定义、合约乘数、最小变动价位、交易日历、涨跌停幅度、合约挂牌与到期日期)属于市场事实,由 meta Module_Package 的 Reference_Data_Store 按生效日期版本化存储;其余取值属于用户选择,由 Config_Manager 从配置文件加载
2. THE Config_Manager SHALL 从配置文件加载 Credential、数据根路径、日志参数、风控上限参数、订阅清单、Tick_Whitelist、Recording_Whitelist、策略参数、回测参数、告警推送参数
3. THE Config_Manager SHALL 不承载市场事实类取值,配置文件中不出现手续费率、保证金率、合约乘数、最小变动价位的取值
4. THE Config_Manager SHALL 将 Credential 与穿透式监管的 AppID、AuthCode 存放在独立的本地配置文件中,该文件路径已列入版本库忽略清单
5. THE Trading_System SHALL 使纳入版本库的全部文件不包含 Credential 明文,版本库中仅保留字段名与占位值的配置模板文件
6. WHERE 环境变量中存在对应的 Credential 配置项,THE Config_Manager SHALL 优先使用环境变量取值而非配置文件取值
7. WHEN Config_Manager 加载配置,THE Config_Manager SHALL 校验必填配置项存在、数值型配置项取值落在允许区间内
8. IF 必填配置项缺失或数值型配置项取值超出允许区间,THEN THE Config_Manager SHALL 终止启动流程并输出包含配置项名称与问题描述的错误信息
9. WHEN Log_Service 记录包含 Credential 字段的内容,THE Log_Service SHALL 将该字段取值替换为固定掩码文本
10. THE Config_Manager SHALL 提供在运行期间重新加载风控上限参数、Tick_Whitelist、Recording_Whitelist 的接口
11. FOR ALL 由配置文件层加载且未被环境变量覆盖的配置对象,执行序列化为配置文件再解析的操作后,得到的配置对象 SHALL 与原对象在全部字段上相等(round-trip 属性)

### Requirement 23: GUI 集成范围

**User Story:** 作为个人交易者,我希望复用 VN Trader 现成界面作为监控外壳,以便把开发精力集中在数据与策略上。

#### Acceptance Criteria

1. THE Trading_System SHALL 将 Recorder_Process 与 Live_Process 实现为独立的 headless 进程,各自具备独立的启动入口,不以图形界面为启动前提
2. THE Recorder_Process SHALL 支持在与 Live_Process 不同的机器上独立部署运行
3. THE Trading_System SHALL 提供命令行入口以启动、停止、查询 Recorder_Process 与 Live_Process
4. THE Monitor_Shell SHALL 展示 State_Snapshot 与事件流文件的内容,展示项包含行情与交易连接状态、已订阅合约数量、当日落库数量、各策略实例状态与持仓、当日盈亏、Halt_State 状态、未确认告警
5. WHEN Monitor_Shell 启动或退出,THE Recorder_Process 与 Live_Process SHALL 不受影响且不中断
6. THE Trading_System SHALL 使 Monitor_Shell 的实现可被替换而无需修改 Recorder_Process 与 Live_Process 的源码
7. THE Trading_System SHALL 复用 vn.py CtaBacktester 模块或命令行接口提交回测与参数优化任务
8. THE Trading_System SHALL 排除自研 K 线图表绘制、画线工具与指标可视化界面,看盘由外部行情软件承担
9. WHEN Recorder_Process 接收到停止指令,THE Recorder_Process SHALL 强制完成当前未完成的 Bar、刷新未写入的数据缓冲、断开 CTP 连接后退出
10. WHEN Live_Process 接收到停止指令,THE Live_Process SHALL 依次停止全部运行中的策略实例、撤销全部活动委托、持久化策略状态与委托流水、断开 CTP 连接后退出
11. IF Recorder_Process 或 Live_Process 异常退出,THEN THE Trading_System SHALL 在下次启动时从 Ingest_Manifest 与委托流水恢复至一致状态

### Requirement 24: 模块化架构约束

**User Story:** 作为个人交易者,我希望模块之间物理隔离且依赖清晰,以便后续修改单个模块时只需进入对应文件夹并降低上下文体积。

#### Acceptance Criteria

1. THE Trading_System SHALL 将每个子系统实现为一个独立 Module_Package,Module_Package 位于项目源码目录下的独立子文件夹
2. THE Trading_System SHALL 为每个 Module_Package 分配一个层级编号,并使导入依赖仅由高层级指向低层级
3. THE Trading_System SHALL 使每个 Module_Package 通过该文件夹内的 `__init__.py` 显式声明对外暴露的接口名称集合
4. THE Trading_System SHALL 使跨 Module_Package 的导入语句仅引用目标 Module_Package 显式声明的接口名称
5. THE Trading_System SHALL 使 Module_Package 之间的导入依赖关系构成有向无环图(无循环依赖不变式)
6. THE Trading_System SHALL 使行情推送、委托回报、成交回报、持仓变动这四类异步事件通过 EventEngine 传递,事件类型常量集中定义在共享常量 Module_Package 中
7. THE Trading_System SHALL 使交易日判定、配置读取、参考数据查询、历史数据查询这四类交互通过显式函数调用完成,不经由 EventEngine
8. THE Trading_System SHALL 在跨 Module_Package 的接口边界使用类型协议声明,使调用方可仅依据协议声明实现而无需读取被调用方的实现代码
9. WHEN 开发者新增一个 Module_Package,THE Trading_System SHALL 在不修改其他 Module_Package 源码的前提下加载该模块
10. THE Trading_System SHALL 提供依赖检查脚本,该脚本在检测到循环依赖、层级违规或跨模块非公开接口引用时返回非零退出码
11. THE Trading_System SHALL 使单个源文件的行数不超过 400 行
12. THE Trading_System SHALL 为每个 Module_Package 提供可独立执行的测试命令
13. THE Trading_System SHALL 使 Strategy 所在 Module_Package 的导入语句不包含任何交易框架名称,该约束由依赖检查脚本强制
14. THE Trading_System SHALL 使 Monitor_Shell 所在 Module_Package 的导入依赖仅限于共享数据结构 Module_Package 与状态读取 Module_Package

### Requirement 25: 数据规模、容量与数据资产保全

**User Story:** 作为个人交易者,我希望系统在当前存储能力内稳定运行、自建数据资产不因故障丢失,并在未来扩展订单流研究时无需改动架构。

#### Acceptance Criteria

1. THE Trading_System SHALL 在单机 Windows 环境下以单账户单实例方式运行
2. THE Trading_System SHALL 使当日全部 Bar 写入失败记录落盘至兜底文件,且每条失败记录可经重放接口重新写入 Data_Store
3. THE Trading_System SHALL 提供当日落库统计与预期数量的比对接口,输出 Recording_Whitelist 内各合约的已落库 Bar 条数、真实缺失条数、写入失败条数
4. THE Data_Store SHALL 将 tick 数据以列式文件格式按 Trading_Day 分区存储,不以单一关系数据库文件承载 tick 数据
5. THE Data_Store SHALL 将 Bar 数据以列式文件格式按品种与年份分区存储,单个分区内按合约代码与时间戳排序
6. THE Trading_System SHALL 分离小型可变状态的所有权:Data_Store 的 DuckDB 仅承载 Ingest_Manifest、Provenance_Table 与质量标记数据集;Reference_Data_Store 承载 Roll_Map 与其他参考事实;Runtime_State_Store 承载策略状态;Alert_Service 将告警记录追加至事件流文件
7. THE Trading_System SHALL 使 Tick_Whitelist 的合约数量上限由配置项 `storage.max_tick_symbols` 控制,默认取值为 20
8. WHEN Tick_Whitelist 的合约数量增加,THE Trading_System SHALL 在仅修改配置文件的前提下扩大 tick 落库范围
9. THE Trading_System SHALL 提供存储占用统计接口,统计内容包含 Bar 记录数、tick 记录数、Raw_Layer 字节大小、Curated_Layer 字节大小、关系型存储文件字节大小
10. IF 数据根目录字节大小超过配置项 `storage.warn_size_gb` 指定阈值(默认 200 GB),THEN THE Trading_System SHALL 向 Alert_Service 发布存储容量告警事件
11. THE Trading_System SHALL 提供按合约代码与日期区间导出与删除 Curated_Layer 数据的接口,用于人工归档与容量管理
12. THE Trading_System SHALL 不提供针对 Raw_Layer 的删除接口
13. THE Trading_System SHALL 提供将 Raw_Layer、委托流水与策略状态同步至外部存储位置的备份接口,备份操作以增量方式执行
14. THE Trading_System SHALL 提供备份校验接口:Raw_Layer 文件的校验和与 Ingest_Manifest 比对,委托流水与策略状态的校验和与备份操作生成的 Backup_Manifest 比对;接口 SHALL 输出缺失、校验和不一致与无法读取的文件清单
15. WHEN 扩大 Tick_Whitelist 以支持订单流研究,THE Trading_System SHALL 在不修改 Module_Package 划分与既有模块源码的前提下完成扩大

### Requirement 26: 设计文档与可审阅性

**User Story:** 作为个人交易者,我希望系统的设计意图与决策理由被显式记录,以便在多次版本迭代后,我本人或外部审阅者能快速理解设计并讨论改进方案。

#### Acceptance Criteria

1. THE Trading_System SHALL 在项目根目录提供仓库地图文档,内容包含每个 Module_Package 的职责摘要、公开接口名称、允许的依赖层级、测试命令位置
2. THE Trading_System SHALL 为每个 Module_Package 提供说明文档,文档小节顺序固定,内容包含职责、公开接口、不变式、禁止导入项及其理由、已否决的备选方案及否决理由、已知局限及其重做条件、测试命令
3. THE Trading_System SHALL 提供架构决策记录集合,每条记录包含背景约束、所采纳决策、采纳理由、已放弃的备选方案、后果、以及该决策是否为承重决策的标注
4. THE Trading_System SHALL 使架构决策记录仅追加不修改,决策变更时新增记录并将被取代的记录标注为已取代
5. THE Trading_System SHALL 提供审阅入口文档,内容包含建议阅读顺序、系统的核心约束清单、已知未解决问题清单
6. FOR ALL Module_Package,该 Module_Package 说明文档中列出的公开接口名称集合 SHALL 与该 Module_Package `__init__.py` 声明的接口名称集合完全一致
7. THE Trading_System SHALL 提供校验脚本,该脚本在检测到说明文档与 `__init__.py` 声明不一致、或架构决策记录引用指向不存在的记录时返回非零退出码
8. WHEN 某 Module_Package 的公开接口发生变更,THE Trading_System SHALL 要求该变更与对应说明文档的更新在同一次版本提交内完成
9. THE Trading_System SHALL 纳入版本控制管理,使设计演化过程可追溯
10. THE Trading_System SHALL 使说明文档不复述代码与类型标注已能表达的信息,文档内容限于设计理由、约束与取舍

### Requirement 27: 合约代码规范化

**User Story:** 作为个人交易者,我希望系统内部对同一合约只有一种写法,以便避免因代码格式差异导致的数据错配与报单错误。

#### Acceptance Criteria

1. THE Trading_System SHALL 定义 Canonical_Symbol 为系统内部唯一的合约表示形式,格式为品种代码加 4 位年月加交易所后缀
2. THE Trading_System SHALL 将外部写法转换为 Canonical_Symbol 的逻辑与将 Canonical_Symbol 转换为外部写法的逻辑集中在单一 Module_Package 内,其他模块不包含合约代码的字符串拼接与截取
3. WHEN 调用方传入郑州商品交易所的 3 位年月合约代码与参考日期,THE Trading_System SHALL 依据参考日期推断年份世纪并输出 4 位年月的 Canonical_Symbol
4. THE Trading_System SHALL 使推断结果与合约挂牌日期、到期日期构成的有效区间校验一致
5. IF 某 3 位年月合约代码在给定参考日期下对应多个有效合约,THEN THE Trading_System SHALL 输出错误而非返回其中任一推断结果
6. WHEN 向 CTP 接口提交合约代码,THE Trading_System SHALL 将 Canonical_Symbol 转换为该接口要求的写法,包含郑州商品交易所要求的 3 位年月形式
7. THE Trading_System SHALL 按各交易所惯例处理品种代码的大小写,并使同一合约在不同大小写输入下归一至同一个 Canonical_Symbol
8. THE Trading_System SHALL 识别组合合约与跨期套利合约的代码形式,并使其不被转换为普通合约的 Canonical_Symbol
9. FOR ALL 合法的 Canonical_Symbol,执行转换为某接口写法再转换回 Canonical_Symbol 的操作后,结果 SHALL 与原值相等(round-trip 属性)

### Requirement 28: 主力连续合约构造与换月复权

**User Story:** 作为个人交易者,我希望获得跨越多年的连续价格序列,以便对存续期仅数月的期货合约执行长周期回测。

#### Acceptance Criteria

1. THE Continuous_Series_Builder SHALL 输出 Roll_Map 与复权序列两个独立产物
2. THE Continuous_Series_Builder SHALL 按配置的换月规则确定各交易日的活跃合约,默认规则为持仓量最大者
3. WHEN 判定某交易日的活跃合约,THE Continuous_Series_Builder SHALL 仅使用该交易日之前的数据,不使用该交易日及之后的数据
4. THE Continuous_Series_Builder SHALL 要求候选合约的持仓量在配置项 `continuous.confirm_days`(默认 2 个交易日)内持续超过在任合约后方执行换月
5. THE Continuous_Series_Builder SHALL 使 Roll_Map 中的合约到期月份随交易日单调递增,不允许换回更近月份的合约
6. THE Continuous_Series_Builder SHALL 支持无复权、前复权、后复权、比例复权四种 Adjustment_Method
7. THE Continuous_Series_Builder SHALL 将换月规则标识与 Adjustment_Method 标识编入复权序列的存储路径,使不同规则与复权方式的产物互不覆盖
8. WHEN 构造复权序列,THE Continuous_Series_Builder SHALL 输出 Roll_Event 记录集合,每条记录包含换月交易日、换出合约、换入合约
9. THE Trading_System SHALL 以逐合约原始 Bar 作为真相来源,并使复权序列可由逐合约原始 Bar 与 Roll_Map 重新构造
10. THE Trading_System SHALL 使连续合约标识不被用于委托提交,Order_Manager 接收到连续合约标识时拒绝该委托并记录拒绝原因
11. WHEN Backtest_Engine 使用连续合约序列,THE Backtest_Engine SHALL 依据 Roll_Event 计算换月成本并计入回测结果
12. FOR ALL 相同的换月规则、Adjustment_Method 与输入数据,重复执行构造 SHALL 得到完全相同的 Roll_Map 与复权序列(确定性属性)

### Requirement 29: 费用与保证金计算

**User Story:** 作为个人交易者,我希望回测与实盘使用同一套费用计算逻辑,以便回测结果的费用假设与实盘实际扣费一致。

#### Acceptance Criteria

1. THE Trading_System SHALL 将手续费、滑点、保证金占用的计算实现为独立的 Cost_Model,并使 Backtest_Engine 与 Live_Trading_Engine 调用同一批函数
2. THE Cost_Model SHALL 支持按手固定金额与按成交金额比例两种手续费形态,并支持二者并存
3. THE Cost_Model SHALL 使平今手续费率与平昨手续费率可分别取值
4. WHEN Cost_Model 计算某笔成交的手续费,THE Cost_Model SHALL 以 Canonical_Symbol、开平标志、成交价格、成交数量、参考日期为入参
5. THE Cost_Model SHALL 使费率取值来自参考数据集中该合约在参考日期生效的版本,不使用当前日期生效的版本计算历史成交
6. THE Cost_Model SHALL 支持申报费形态的费用项
7. THE Cost_Model SHALL 提供按 Settlement_Price 计算持仓占用保证金的接口
8. FOR ALL 相同的入参,Backtest_Engine 与 Live_Trading_Engine 经 Cost_Model 得到的手续费计算结果 SHALL 相等
9. THE Trading_System SHALL 提供实盘成交的费用对账接口,该接口比对 Cost_Model 计算值与期货公司实际扣费值,并输出逐笔差额与差额占比
10. IF 费用对账的差额占比超过配置项 `costs.reconcile_tolerance`(默认 0.05),THEN THE Trading_System SHALL 向 Alert_Service 发布费用模型偏差事件

### Requirement 30: 参考数据版本化

**User Story:** 作为个人交易者,我希望费率、保证金率与合约参数按生效日期存储,以便回测使用历史上真实生效的取值。

#### Acceptance Criteria

1. THE Reference_Data_Store SHALL 以带生效日期区间的形式存储手续费率、保证金率、合约乘数、最小变动价位、合约挂牌日期、合约到期日期、涨跌停幅度、Settlement_Price
2. WHEN 调用方传入 Canonical_Symbol 与参考日期,THE Reference_Data_Store SHALL 返回该合约在该参考日期生效的参数取值
3. WHEN CTP 交易连接登录成功,THE Trading_System SHALL 查询本账户的合约手续费率与保证金率并将查询结果写入 Raw_Layer
4. THE Trading_System SHALL 由 Raw_Layer 中历次费率查询结果的序列构建带生效日期的费率参考数据集
5. THE Trading_System SHALL 以本账户 CTP 查询结果作为手续费率与保证金率的首选来源,交易所公告作为次选来源
6. WHEN 采集交易所日行情文件,THE Trading_System SHALL 从该文件提取 Settlement_Price、涨跌停价格与持仓量并写入参考数据集
7. IF 某参数在请求的参考日期上无生效记录,THEN THE Reference_Data_Store SHALL 输出错误而非返回最近可用记录
8. THE Reference_Data_Store SHALL 提供公开查询接口,支持按合约与参考日期查询该日生效的全部参数取值

### Requirement 31: 合约到期与换月执行

**User Story:** 作为个人交易者,我希望系统在合约临近到期时自动平仓或换月,以避免持仓进入交割月而被强制平仓或产生交割义务。

#### Acceptance Criteria

1. THE Expiry_Policy SHALL 按品种配置强制平仓提前天数,配置项为 `expiry.force_close_days_before`,默认取值为 5 个交易日
2. WHEN 某合约距其到期日的剩余交易日数小于或等于该品种的强制平仓提前天数,THE Risk_Manager SHALL 拒绝该合约的全部开仓委托并返回临近到期原因
3. WHEN 某合约距其到期日的剩余交易日数小于或等于该品种的强制平仓提前天数且该合约存在持仓,THE Live_Trading_Engine SHALL 提交平仓委托并向 Alert_Service 发布到期强制平仓事件
4. WHERE 配置项 `expiry.auto_roll_enabled` 取值为 `true`,THE Live_Trading_Engine SHALL 在平仓当前合约后于 Roll_Map 给出的新合约上建立等量持仓
5. THE Live_Trading_Engine SHALL 执行到期强制平仓,不以策略实例是否期望继续持有作为执行前提
6. IF 到期强制平仓委托未在配置项 `expiry.close_timeout_minutes`(默认 30 分钟)内全部成交,THEN THE Trading_System SHALL 向 Alert_Service 发布到期平仓未完成事件
7. THE Trading_System SHALL 在每个 Trading_Day 开始时对全部持仓合约执行到期检查

### Requirement 32: 失败分类与停机策略

**User Story:** 作为个人交易者,我希望不同严重程度的故障有明确不同的处置方式,以避免系统因琐碎异常中断,或带着严重故障继续交易。

#### Acceptance Criteria

1. THE Trading_System SHALL 将运行期故障划分为五类:需立即停机并等待人工放行、需停止单个策略实例、需拒绝当前操作并通知策略、需有界重试、仅记录并跳过
2. THE Trading_System SHALL 使异常类型定义与故障分类一一对应,处置方式可由异常类型确定
3. THE Trading_System SHALL 将对账不符、穿透式监管校验失败、风控模块自身异常、交易日历数据缺失(请求日期超出交易日历覆盖范围)归入需立即停机类
4. THE Trading_System SHALL 将策略回调异常归入需停止单个策略实例类
5. THE Trading_System SHALL 将风控否决、可用资金不足、涨跌停拦截归入需拒绝并通知策略类
6. THE Trading_System SHALL 将数据写入失败、CTP 查询超时、行情连接中断归入需有界重试类,且每类重试均配置次数上限
7. THE Trading_System SHALL 将单条 Tick 时间戳越界、外部数据源单条记录字段缺失、单个品种在参考日期上无生效的 Trading_Session 定义归入仅记录并跳过类,并以计数形式汇总而非逐条发布告警事件;其中品种级时段定义缺失须按品种汇总并发布需人工关注类告警
8. IF 任一需有界重试类故障的重试次数达到上限,THEN THE Trading_System SHALL 将该故障升级为需立即停机类或需停止单个策略实例类,不无限重试
9. WHEN Trading_System 进入 Halt_State,THE Trading_System SHALL 在 State_Snapshot 中标记该状态与进入原因

### Requirement 33: 可测试性与确定性

**User Story:** 作为个人交易者,我希望时间相关逻辑与边界场景可被确定性地测试,以便在修改共用逻辑时有可靠的回归保障。

#### Acceptance Criteria

1. THE Trading_System SHALL 提供 Clock 抽象,并使各子系统通过 Clock 获取当前时间
2. THE Trading_System SHALL 不在 Clock 实现之外的模块源码中直接调用系统时钟接口
3. WHEN 执行测试,THE Trading_System SHALL 支持注入固定时间或可推进时间的 Clock 实现
4. THE Trading_System SHALL 提供 Golden_Fixture 测试数据集,覆盖夜盘跨自然日、周五夜盘归属、节前夜盘停盘、春节前后交易日边界、郑州商品交易所 3 位年月合约、主力换月、涨跌停封板、冷门合约零成交分钟八类场景
5. THE Trading_System SHALL 使 Golden_Fixture 内容纳入版本控制且不随代码变更而修改
6. THE Trading_System SHALL 为交易日映射函数与合约代码转换函数提供表驱动测试,测试用例的预期值由人工核对确定
7. THE Trading_System SHALL 为每个指标提供标量形式与序列形式两种实现,并提供断言二者在随机输入下结果一致的测试
8. WHEN 更换 Backtest_Engine 实现,THE Trading_System SHALL 提供跨引擎一致性测试,该测试断言同一 Strategy 在同一数据上经不同引擎产出的成交记录与资金曲线在浮点误差内相等
9. THE Trading_System SHALL 提供未来函数守卫测试,该测试断言 Roll_Map 的每个换月决策仅使用换月交易日之前的数据

### Requirement 34: 缺陷预防机制

**User Story:** 作为个人交易者,我希望缺陷预防手段按可靠性分级投入,以便在借助大语言模型开发的前提下,领域逻辑的正确性不依赖模型自身的理解。

#### Acceptance Criteria

1. THE Trading_System SHALL 将缺陷预防手段划分为四级,按可靠性由高至低依次为:确定性检查、预期值经人工核对的表驱动测试、与外部真相的交叉校验、定向的自动化代码审查
2. THE Trading_System SHALL 使凡可由脚本判定的约束均由脚本检查,不以自动化代码审查替代脚本检查
3. THE Trading_System SHALL 使第一级确定性检查可在单次代码变更后执行完毕,执行内容包含依赖层级检查、文档与 `__init__.py` 一致性检查、静态类型检查、代码格式检查
4. THE Trading_System SHALL 使领域逻辑测试用例的预期值来源于交易所公告、交易日历、券商确认费率等系统外部权威资料
5. THE Trading_System SHALL 不以生成被测实现的同一模型产出该实现的测试预期值
6. WHEN 由模型编写领域逻辑测试,THE Trading_System SHALL 要求模型仅编写测试输入与测试结构、将预期值标记为待填,由开发者填入经外部资料核对的取值
7. IF 某领域逻辑测试的预期值处于待填标记状态,THEN THE Trading_System SHALL 使该测试的执行结果为失败而非通过
8. THE Trading_System SHALL 提供第三级交叉校验,校验项包含自建聚合日线与交易所日行情文件的比对、Cost_Model 计算费用与本账户 CTP 查询费率的比对、回测建模成交与实盘真实成交的比对
9. WHEN 执行自动化代码审查,THE Trading_System SHALL 向审查方提供系统外部的判据,判据取值为对应需求的验收标准原文、交易所规则原文、或券商确认的参数表
10. THE Trading_System SHALL 不以无外部判据的开放式提问方式执行自动化代码审查
11. THE Trading_System SHALL 使自动化代码审查在 Module_Package 完成与 Phase 完成两个节点执行,不作为单次代码变更的前置条件
12. WHEN 执行验收标准覆盖检查,THE Trading_System SHALL 输出目标 Module_Package 所对应需求中尚无测试覆盖的验收标准条目清单
