"""Shared research boards classified by disclosed portfolios, never fund titles."""
import copy
import math
import re
import threading
from contextlib import contextmanager
from functools import wraps
from collections import Counter
from decimal import Decimal

SCHEMA_VERSION = 9
_catalog_lock = threading.RLock()


def catalog_synchronized(function):
    @wraps(function)
    def synchronized(*args, **kwargs):
        with _catalog_lock:
            return function(*args, **kwargs)
    return synchronized
NAME_BASIS = '按来源资产类型与披露持仓归类；基金名称只作展示，非官方行业分类'

FINANCIAL_THEMES = [
    ('fintech', '金融科技', r'金融科技|互联网金融|数字金融|FINTECH|金融IT',
     '金融科技主题：按金融科技、互联网金融、数字金融等名称线索识别；不把所有“新金融”都视为科技主题。'),
    ('financial_real_estate', '金融地产', r'金融.*地产|地产.*金融',
     '金融与房地产复合主题；与纯银行、纯券商、纯保险以及纯房地产分开研究。'),
    ('diversified_finance', '多元金融', r'多元金融|信托|融资租赁|金融租赁|消费金融',
     '按多元金融、信托、金融租赁等明确名称线索识别；没有对应公开样本时保留空缺。'),
    ('nonbank', '证券保险', r'非银|(?:证券|券商).*保险|保险.*(?:证券|券商)',
     '金融细分中的非银或证券保险组合主题；不与单一券商、单一保险基金混排。'),
    ('banking', '银行', r'银行',
     '金融细分中的银行股票主题；承担权益波动，不是银行存款。'),
    ('securities', '证券与券商', r'证券|券商',
     '金融细分中的单一证券、券商主题；证券保险组合另列为非银综合。'),
    ('insurance', '保险', r'保险',
     '金融细分中的单一保险股票主题；不是保险合同或保本产品。'),
    ('finance', '综合金融', r'金融',
     '仅能从名称识别为宽泛金融主题，包括金融精选、新金融等；不能确认单一子行业时保留综合分类。'),
]

INDUSTRIES = [
    ('liquor', '白酒', r'白酒'),
    ('cxo', 'CXO', r'CXO|医药研发外包|医药外包|医疗研发外包'),
    ('food_beverage', '食品饮料', r'食品|饮料|食饮'),
    ('innovative_drug', '创新药', r'创新药'),
    ('brain_computer', '脑机接口', r'脑机接口|脑机交互'),
    ('medical', '医疗', r'医疗|医疗器械|医疗服务'),
    ('home_appliances', '家用电器', r'家用电器|家电'),
    ('eldercare', '养老产业', r'养老产业|养老服务|银发经济'),
    ('consumer_electronics', '消费电子', r'消费电子'),
    ('gold_equity', '黄金股', r'黄金股|黄金矿业|黄金产业|黄金采矿|黄金资源'),
    ('compute_leasing', '算力租赁', r'算力租赁|租赁算力'),
    ('nuclear_fusion', '可控核聚变', r'可控核聚变|核聚变'),
    ('cloud_computing', '云计算', r'云计算|云服务'),
    ('domestic_computing', '国产算力', r'国产算力|自主算力'),
    ('memory_chip', '存储芯片', r'存储芯片|存储半导体|半导体存储|存储器芯片'),
    ('semiconductor_equipment', '半导体材料设备', r'半导体材料|半导体设备|半导体.*材料.*设备|芯片材料|芯片设备|集成电路设备'),
    ('semiconductor', '半导体', r'半导体|芯片|集成电路'),
    ('pcb', 'PCB', r'PCB|印制电路板|印刷电路板'),
    ('cpo', 'CPO', r'CPO|光电共封装|光电合封'),
    ('mlcc', 'MLCC', r'MLCC|多层陶瓷电容|多层片式陶瓷电容'),
    ('ai_application', 'AI应用', r'AI应用|人工智能应用'),
    ('ai', '人工智能', r'人工智能|AI(?:产业|主题)'),
    ('robotics', '机器人', r'机器人|智能驾驶'),
    ('communication', '通信', r'通信|通讯|5G|6G'),
    ('technology', '大科技', r'大科技|科技|计算机|电子|数字经济|软件|信息技术|互联网'),
    ('solid_state_battery', '固态电池', r'固态电池|全固态电池|半固态电池'),
    ('energy_storage', '储能', r'储能'),
    ('photovoltaic', '光伏', r'光伏|太阳能'),
    ('renewable', '新能源', r'新能源|光伏|电池|碳中和|储能|风电'),
    ('healthcare', '医药', r'医药|生物|健康'),
    ('consumer', '消费', r'消费|家电'),
    *((key, label, pattern) for key, label, pattern, _ in FINANCIAL_THEMES),
    ('commercial_aerospace', '商业航天', r'商业航天'),
    ('defense', '军工', r'军工|国防|航空航天|航天|卫星|大飞机'),
    ('real_estate', '房地产', r'房地产|地产'),
    ('infrastructure', '基建', r'基建|基础设施|建筑|建材|工程建设'),
    ('agriculture', '农林牧渔', r'农业|农林牧渔|种业|养殖|畜牧|农牧|粮食'),
    ('environment', '环保', r'环保|环境治理|生态环境'),
    ('grid_equipment', '电网设备', r'电网设备|电力设备|智能电网|电网装备'),
    ('power', '电力', r'电力|水电|绿电|绿色电力'),
    ('utilities', '电力与公用事业', r'公用事业|水务|燃气'),
    ('transport', '交通运输', r'交通运输|交通|物流|航运|航空|运输|快递|港口'),
    ('media', '传媒游戏', r'传媒|游戏|文化|影视|娱乐'),
    ('travel', '旅游与酒店', r'旅游|酒店|文旅|休闲'),
    ('auto_vehicle', '汽车整车', r'汽车整车|整车|汽车制造'),
    ('automotive', '汽车', r'汽车|智能车|车联网'),
    ('construction_machinery', '工程机械', r'工程机械'),
    ('advanced_manufacturing', '先进制造', r'先进制造|高端制造|智能制造'),
    ('manufacturing', '机械与高端制造', r'机械|高端装备|装备|制造|工业母机|工业4'),
    ('chemicals', '化工', r'化工|化学|新材料'),
    ('oil_gas', '油气资源', r'油气|石油|天然气'),
    ('coal', '煤炭', r'煤炭|煤业'),
    ('lithium_mining', '锂矿', r'锂矿|锂资源'),
    ('steel', '钢铁', r'钢铁|钢材'),
    ('rare_earth_magnet', '稀土永磁', r'稀土|永磁'),
    ('nonferrous', '有色金属', r'有色金属|有色'),
    ('resources', '资源能源综合', r'有色|资源|煤炭|能源|矿|钢铁|稀土'),
]

# These are narrower overseas themes, separate from broad regional equity/mixed
# boards. Prefixes preserve the existing overseas/FX evidence restrictions.
OVERSEAS_THEMES = [
    ('overseas_hk_innovative_drug', '港创新药', r'港创新药|(?:港股|香港|恒生).*创新药|创新药.*(?:港股|香港)',
     ['港股创新药', '香港创新药', '恒生创新药']),
    ('overseas_hugangshen_consumer', '沪港深消费', r'(?:沪港深|沪深港).*消费|消费.*(?:沪港深|沪深港)',
     ['沪深港消费', '跨市场消费']),
    ('overseas_hang_seng_technology', '恒生科技', r'恒生科技|HSTECH', ['恒生科技指数', '香港科技']),
    ('overseas_hk_internet', '港股互联', r'(?:港股|香港|恒生|中概|中国).*(?:互联网|互联)|(?:互联网|互联).*(?:港股|香港)',
     ['港股互联网', '中概互联网', '中国互联网']),
    ('overseas_hk_dividend', '港股红利', r'(?:港股|香港|恒生|沪港深|沪深港).*(?:红利|高股息)|(?:红利|高股息).*(?:港股|香港)',
     ['香港红利', '恒生红利', '港股高股息']),
    ('overseas_healthcare', '海外医药', r'医药|医疗|生物|健康|创新药', ['全球医药', '海外医疗', '港股医药']),
    ('overseas_hang_seng', '恒生', r'恒生(?:指数|ETF|交易型|联接)|恒生(?:[ABC]|人民币|美元|港币)*$|HANG.?SENG.?INDEX',
     ['恒生指数', '香港宽基']),
    ('overseas_sp500', '标普', r'标普|S[&＆]P\s*500|S\s*P\s*500', ['标普500', 'S&P500']),
    ('overseas_nasdaq', '纳指', r'纳斯达克|纳指|NASDAQ', ['纳斯达克', '纳斯达克100', 'NASDAQ']),
    ('overseas_asia_pacific', '亚太', r'亚太|亚洲|东南亚', ['亚洲市场', '东南亚市场']),
]

REFERENCE_ORDER = [
    'sector_liquor', 'sector_food_beverage', 'overseas_hk_internet', 'overseas_hk_dividend',
    'sector_cxo', 'sector_oil_gas', 'overseas_hugangshen_consumer', 'sector_brain_computer',
    'sector_consumer', 'sector_transport', 'overseas_hang_seng', 'overseas_hang_seng_technology',
    'sector_real_estate', 'overseas_healthcare', 'style_dividend_low_volatility', 'sector_medical',
    'sector_home_appliances', 'dividend', 'sector_coal', 'sector_eldercare', 'style_cashflow',
    'sector_lithium_mining', 'sector_healthcare', 'sector_banking', 'sector_solid_state_battery',
    'sector_innovative_drug', 'sector_chemicals', 'money', 'sector_infrastructure', 'short_bond',
    'index_beijing', 'long_bond', 'convertible_bond', 'fixed_income_plus', 'index_sse50',
    'sector_steel', 'overseas_sp500', 'sector_rare_earth_magnet', 'sector_agriculture', 'style_bluechip',
    'sector_renewable', 'sector_auto_vehicle', 'overseas_hk_innovative_drug', 'sector_nonferrous',
    'index_csi300', 'sector_power', 'sector_energy_storage', 'sector_nonbank', 'gold', 'index_csi500',
    'overseas_asia_pacific', 'sector_photovoltaic', 'sector_construction_machinery', 'style_microcap',
    'sector_robotics', 'sector_grid_equipment', 'style_quant', 'overseas_nasdaq',
    'sector_commercial_aerospace', 'style_small_micro_quant', 'sector_advanced_manufacturing',
    'sector_memory_chip', 'sector_defense', 'sector_gold_equity', 'index_chinext', 'sector_mlcc',
    'sector_cloud_computing', 'index_star', 'sector_consumer_electronics', 'sector_technology',
    'index_dual50', 'sector_compute_leasing', 'sector_ai', 'sector_media', 'sector_nuclear_fusion',
    'sector_domestic_computing', 'sector_semiconductor', 'sector_fintech', 'sector_ai_application',
    'sector_communication', 'sector_semiconductor_equipment', 'sector_pcb', 'sector_cpo',
]

INDEX_THEMES = [
    ('index_dual50', '双创50', r'双创50|科创创业50', ['中证科创创业50', '科创创业50']),
    ('index_beijing', '北证', r'北证|北京证券交易所', ['北证50', '北京证券交易所50']),
    ('index_sse50', '上证50', r'上证\s*50|SSE\s*50', ['上证50指数', 'SSE50']),
    ('index_csi300', '沪深300', r'沪深\s*300|CSI\s*300', ['沪深300指数', 'CSI300']),
    ('index_csi500', '中证500', r'中证\s*500|CSI\s*500', ['中证500指数', 'CSI500']),
    ('index_chinext', '创业板', r'创业板|创业大盘|创业成长|创业创新', ['创业板指', '创业板50']),
    ('index_star', '科创板', r'科创板|科创\s*50|科创\s*100|科创综指', ['科创50', '科创100', '科创综指']),
]

STYLE_THEMES = [
    ('style_small_micro_quant', '小微盘量化', r'(?:小微盘|微盘|小盘).*量化|量化.*(?:小微盘|微盘|小盘)', ['微盘量化', '小盘量化']),
    ('style_dividend_low_volatility', '红利低波', r'(?:红利|高股息).*低波|低波.*(?:红利|高股息)', ['红利低波动', '低波红利']),
    ('dividend', '红利', r'红利|高股息', ['高股息', '红利策略']),
    ('style_cashflow', '现金流', r'现金流', ['自由现金流', '现金流策略']),
    ('style_bluechip', '蓝筹', r'蓝筹', ['蓝筹精选', '蓝筹策略']),
    ('style_microcap', '微盘股', r'微盘|小微盘', ['微盘', '小微盘']),
    ('style_quant', '量化', r'量化', ['量化策略', '量化选股']),
]

ALIASES = {
    'sector_cxo': ['医药研发外包', '医药外包'],
    'sector_liquor': ['白酒行业'], 'sector_food_beverage': ['食品', '饮料', '食饮'],
    'sector_medical': ['医疗器械', '医疗服务'], 'sector_healthcare': ['生物医药', '制药'],
    'sector_innovative_drug': ['创新医药'], 'sector_oil_gas': ['石油', '天然气'],
    'sector_transport': ['物流', '航运', '航空', '快递', '港口'],
    'sector_gold_equity': ['黄金股票', '黄金矿业', '黄金产业', '黄金资源'],
    'sector_compute_leasing': ['租赁算力'], 'sector_nuclear_fusion': ['核聚变'],
    'sector_domestic_computing': ['自主算力'], 'sector_cloud_computing': ['云服务'],
    'sector_semiconductor': ['芯片', '集成电路'],
    'sector_semiconductor_equipment': ['半导体设备', '半导体材料', '芯片设备'],
    'sector_pcb': ['印制电路板', '印刷电路板'], 'sector_cpo': ['光电共封装', '光电合封'],
    'sector_ai': ['AI产业', '人工智能主题'], 'sector_ai_application': ['人工智能应用'],
    'sector_communication': ['通讯', '5G', '6G'], 'sector_media': ['传媒', '游戏', '影视'],
    'sector_fintech': ['互联网金融', '数字金融', 'FINTECH'],
    'sector_brain_computer': ['脑机交互'], 'sector_home_appliances': ['家电'],
    'sector_eldercare': ['养老服务', '银发经济'], 'sector_coal': ['煤业'],
    'sector_lithium_mining': ['锂资源'], 'sector_solid_state_battery': ['全固态电池', '半固态电池'],
    'sector_steel': ['钢材'], 'sector_rare_earth_magnet': ['稀土', '永磁'],
    'sector_nonferrous': ['有色'], 'sector_auto_vehicle': ['整车', '汽车制造'],
    'sector_power': ['水电', '绿电', '绿色电力'], 'sector_energy_storage': ['储能产业'],
    'sector_photovoltaic': ['太阳能'], 'sector_construction_machinery': ['工程机械行业'],
    'sector_grid_equipment': ['电力设备', '智能电网', '电网装备'],
    'sector_commercial_aerospace': ['商业航天产业'],
    'sector_advanced_manufacturing': ['高端制造', '智能制造'],
    'sector_memory_chip': ['存储半导体', '半导体存储', '存储器芯片'],
    'sector_mlcc': ['多层陶瓷电容', '多层片式陶瓷电容'],
    'sector_nonbank': ['非银综合（证券保险等）', '非银金融'],
    'sector_infrastructure': ['基建与建材', '基础设施', '建筑建材'],
    'sector_agriculture': ['农业与养殖', '农业', '养殖'],
    'sector_defense': ['军工与航空航天', '国防军工'],
    'sector_technology': ['科技综合', '科技', '数字经济'],
}
REGIONS = [
    ('hk', '港股', r'港股|沪港深|沪深港|恒生|香港|中概'),
    ('us', '美股', r'美国|美股|纳斯达克|纳指|标普|道琼斯'),
    ('jp', '日本', r'日本|日经'),
    ('eu', '欧洲', r'欧洲|德国|法国|英国|欧元区'),
    ('in', '印度', r'印度'),
    ('vn', '越南', r'越南'),
    ('em', '新兴市场', r'新兴市场|新兴经济'),
    ('global', '全球市场', r'全球|国际|环球'),
]

ASSETS = {
    'equity_active': ('综合主动权益', 'broad'),
    'equity_index': ('宽基及其他权益指数', 'broad'),
    'overseas_equity': ('其他海外权益', 'overseas'),
    'overseas_mixed': ('其他海外混合', 'overseas'),
    'overseas_bond': ('海外债券', 'defensive'),
    'gold': ('黄金矿业股票', 'industry'),
    'commodities': ('大宗商品·资源企业股票', 'industry'),
    'convertible_bond': ('可转债', 'defensive'),
    'secondary_bond': ('二级债及混合债', 'defensive'),
    'short_bond': ('短债', 'defensive'),
    'bond': ('纯债及普通债券', 'defensive'),
    'money': ('货币基金', 'defensive'),
    'unclassified': ('类型待核验', 'other'),
}
BOARDS = {}
for key, label, pattern in INDUSTRIES:
    BOARDS['sector_' + key] = {'id': 'sector_' + key, 'label': label, 'group': 'industry',
        'description': label + '方向；名称只用于初筛，展示前需核验披露持仓与本板块的匹配。',
        'aliases': ALIASES.get('sector_' + key, []), 'requires_holdings_match': True}
for key, _, _, description in FINANCIAL_THEMES:
    BOARDS['sector_' + key].update(family='finance', description=description + ' 分类依据为名称和来源类型，实际持仓待核验。')
for key, label, pattern in REGIONS:
    for asset, suffix in [('equity', '权益'), ('mixed', '混合')]:
        identity = 'overseas_' + key + '_' + asset
        BOARDS[identity] = {'id': identity, 'label': label + ' · ' + suffix, 'group': 'overseas',
            'description': '地域按名称初筛，展示前核验披露持仓；海外行情与汇率证据未齐备时仅观察，不用A股行情替代。',
            'aliases': [label], 'requires_holdings_match': True}
for identity, label, pattern, aliases in OVERSEAS_THEMES:
    BOARDS[identity] = {'id': identity, 'label': label, 'group': 'overseas',
        'description': label + '主题；名称只用于初筛，展示前核验披露持仓；海外行情与汇率门槛继续适用。',
        'aliases': aliases, 'requires_holdings_match': True}
for identity, label, pattern, aliases in INDEX_THEMES:
    BOARDS[identity] = {'id': identity, 'label': label, 'group': 'broad',
        'description': label + '方向；名称用于初筛，尚需有效指数成份、目标ETF或基金披露证据核验；不以股票行业标签代替指数资格。',
        'aliases': aliases, 'requires_holdings_match': True}
for identity, label, pattern, aliases in STYLE_THEMES:
    BOARDS[identity] = {'id': identity, 'label': label, 'group': 'style',
        'description': label + '风格方向；名称用于初筛，尚需有效风格或编制方案核验；行业标签不能证明风格、低波或未来收益。',
        'aliases': aliases, 'requires_holdings_match': True}
for key, (label, group) in ASSETS.items():
    BOARDS[key] = {'id': key, 'label': label, 'group': group,
        'description': '在相近资产类型内研究；不将历史趋势分视为收益预测或可执行交易资格。',
        'aliases': [], 'requires_holdings_match': False}
BOARDS['gold'].update(aliases=['黄金', '黄金矿业股票', '黄金采矿'],
    description='黄金矿业公司股票的有限样本研究；不是实物黄金或黄金期货价格。')
BOARDS['commodities'].update(aliases=['大宗商品', '其他商品', '资源企业股票'],
    description='金属采矿与油气资源企业股票的有限样本研究；不是商品现货、期货或全品种商品指数。')
BOARDS['long_bond'] = {'id': 'long_bond', 'label': '中长债', 'group': 'defensive',
    'description': '按明确中长债、长债名称或来源类型初筛；需有效债券资产配置与久期核验，不把普通债券自动视为中长久期。',
    'aliases': ['中长期纯债', '中长期债券', '长债'], 'requires_holdings_match': True}
BOARDS['fixed_income_plus'] = {'id': 'fixed_income_plus', 'label': '固收+', 'group': 'defensive',
    'description': '按明确固收+、固收增强名称初筛；需核验股票、转债及债券资产配置，不能仅凭名称认定低风险。',
    'aliases': ['固收加', '固收增强', '固定收益加'], 'requires_holdings_match': True}
for order, identity in enumerate(REFERENCE_ORDER):
    BOARDS[identity].update(reference_order=order, display_priority=order, reference_board=True)
BOARDS = dict(sorted(BOARDS.items(), key=lambda item: item[1].get('reference_order', len(REFERENCE_ORDER))))


BOARDS['holdings_unclassified'] = {
    'id': 'holdings_unclassified', 'label': '持仓待归类', 'group': 'other',
    'description': '未取得有效持仓，或尚无板块已确认覆盖大部分已披露股票；继续采集持仓，不按基金名称归类。',
    'aliases': [], 'requires_holdings_match': True,
}
for _identity, _board in BOARDS.items():
    if _identity.startswith('sector_'):
        _board['description'] = _board['label'] + '方向；已确认超过一半的已披露股票符合即可，匹配比例越高越优先选择；基金名称不参与归属。'
    elif _board.get('requires_holdings_match'):
        _board['description'] = re.sub(r'名称[^；。]*[；。]', '', _board['description'])


@catalog_synchronized
def register_dynamic_boards(registry, as_of=None):
    """Register a validated, bounded catalogue discovered from stock evidence."""
    from research_dynamic_boards import merge_dynamic_board_registry
    from research_holdings import BOARD_TAGS
    verified = merge_dynamic_board_registry([], registry or [], as_of)
    for board in verified:
        identity = board['id']
        if identity in BOARDS and not BOARDS[identity].get('dynamic'):
            continue
        BOARDS[identity] = copy.deepcopy(board)
        BOARD_TAGS[identity] = set(board['tags'])
    return verified


@contextmanager
def board_catalog_scope(registry, as_of):
    """An old report uses its own catalogue while a new scan discovers boards."""
    from research_holdings import BOARD_TAGS
    with _catalog_lock:
        saved_boards = {key: value for key, value in BOARDS.items() if value.get('dynamic')}
        saved_tags = {key: value for key, value in BOARD_TAGS.items() if key in saved_boards}
        for key in saved_boards:
            BOARDS.pop(key, None)
            BOARD_TAGS.pop(key, None)
        try:
            register_dynamic_boards(registry, as_of)
            yield
        finally:
            for key in [key for key, value in BOARDS.items() if value.get('dynamic')]:
                BOARDS.pop(key, None)
                BOARD_TAGS.pop(key, None)
            BOARDS.update(saved_boards)
            BOARD_TAGS.update(saved_tags)


def _specificity(board):
    """Explicit depth first, then a narrower exact tag set on equal exposure."""
    from research_holdings import BOARD_TAGS
    # The number of accepted aliases is not an industry hierarchy. A single
    # broad provider label (e.g. 医药生物) must not outrank 医疗 at equal exposure.
    broad = {'sector_technology', 'sector_finance', 'sector_financial_real_estate',
             'sector_resources', 'sector_consumer', 'sector_renewable', 'overseas_hang_seng'}
    specialized = {'sector_medical', 'sector_healthcare', 'sector_liquor', 'sector_food_beverage', 'sector_banking',
        'sector_securities', 'sector_insurance', 'sector_diversified_finance', 'sector_fintech',
        'sector_home_appliances', 'sector_consumer_electronics', 'sector_semiconductor',
        'sector_communication', 'sector_grid_equipment', 'sector_power', 'sector_coal',
        'sector_steel', 'sector_photovoltaic', 'sector_energy_storage', 'sector_auto_vehicle',
        'sector_construction_machinery', 'sector_oil_gas', 'sector_nonferrous',
        'overseas_hang_seng_technology', 'overseas_healthcare', 'overseas_hugangshen_consumer'}
    narrow = {'sector_cxo', 'sector_innovative_drug', 'sector_brain_computer',
        'sector_memory_chip', 'sector_semiconductor_equipment', 'sector_pcb', 'sector_cpo',
        'sector_mlcc', 'sector_compute_leasing', 'sector_nuclear_fusion',
        'sector_domestic_computing', 'sector_ai_application', 'sector_solid_state_battery',
        'sector_rare_earth_magnet', 'sector_lithium_mining', 'sector_gold_equity',
        'sector_commercial_aerospace', 'overseas_hk_innovative_drug'}
    identity = board['id']
    known_depth = 0 if identity in broad else 3 if identity in narrow else 2 if identity in specialized else 1
    depth = max(known_depth, board.get('hierarchy_depth') or board.get('specificity') or 0)
    return (-depth, len(BOARD_TAGS.get(board['id'], ())) or 10000)


@catalog_synchronized
def board_matches_for(fund, asset_category, as_of=None):
    """All independently proven portfolios, invariant to the product name.

    Source asset types still separate cash/bonds from equities. An industry
    label is never inferred from a product title, index title or search result.
    """
    from research_holdings import supported_board_ids, verify_board, HOLDINGS_RULE_VERSION, MIN_MATCH_DISCLOSED_PCT
    asset_only = {'money', 'short_bond', 'bond', 'secondary_bond',
                  'convertible_bond', 'overseas_bond', 'gold', 'commodities'}
    if asset_category in asset_only:
        board = dict(BOARDS[asset_category])
        board.update(asset_category=asset_category, classification_method='source_asset_type',
                     classification_basis='按数据源明确资产类型归类；基金名称不参与板块归属，资产类型不等于低风险评级。')
        return [board]
    matches = []
    holdings = fund.get('holdings') if isinstance(fund, dict) else None
    if isinstance(holdings, dict) and holdings.get('status') == 'ok':
        for identity in supported_board_ids():
            if identity not in BOARDS:
                continue
            match = verify_board(fund, identity, as_of=as_of)
            if match['status'] != 'matched':
                continue
            try:
                matched = Decimal(str(match.get('matched_weight_pct')))
                total = Decimal(str(match.get('disclosed_weight_pct')))
                if not (match.get('rule_version') == HOLDINGS_RULE_VERSION
                        and matched.is_finite() and total.is_finite() and 0 < matched <= total
                        and matched * 100 > total * MIN_MATCH_DISCLOSED_PCT):
                    continue
            except Exception:
                continue
            board = dict(BOARDS[identity])
            board.update(asset_category=asset_category, classification_method='disclosed_holdings',
                         board_match=match,
                         classification_basis='仅按有报告期的已披露股票权重及可核验证券分类归类；基金名称不参与。' + match['reason'])
            matches.append(board)
    if matches:
        positions = {identity: index for index, identity in enumerate(BOARDS)}
        matches.sort(key=lambda board: (-Decimal(str(board['board_match']['matched_weight_pct'])) /
                                       Decimal(str(board['board_match']['disclosed_weight_pct'])),
                                       *_specificity(board), positions[board['id']]))
        return matches
    board = dict(BOARDS['holdings_unclassified'])
    board.update(asset_category=asset_category, classification_method='holdings_unresolved',
                 classification_basis='基金名称不参与板块归属；尚无板块已确认覆盖大部分（>50%）已披露股票的有效证据。')
    return [board]


def boards_for(fund, asset_category, as_of=None):
    """Use an explicit reference board, otherwise the highest portfolio match."""
    matches = board_matches_for(fund, asset_category, as_of=as_of)
    primary = copy.deepcopy(matches[0])
    reference = fund.get('reference_candidate') if isinstance(fund, dict) else None
    reference = reference if isinstance(reference, dict) else {}
    requested = reference.get('requested_board_id')
    if reference.get('source_kind') in ('user_reference', 'yangjibao') and requested in BOARDS:
        from research_holdings import verify_board
        primary = copy.deepcopy(BOARDS[requested])
        primary.update(asset_category=asset_category, classification_method='reference_board',
                       board_match=verify_board(fund, requested, as_of=as_of),
                       classification_basis='按养基宝板块分类收录；真实持仓匹配比例独立核验，基金名称仅用于展示。')
    primary['board_comparison'] = [{'id': board['id'], 'label': board['label'],
                                  'matched_disclosed_pct': board.get('board_match', {}).get('matched_disclosed_pct'),
                                  'ratio_is_lower_bound': board.get('board_match', {}).get('ratio_is_lower_bound')}
                                 for board in matches if board.get('board_match')][:6]
    if primary.get('classification_method') == 'disclosed_holdings':
        primary['classification_basis'] = ('按各相关板块的已披露股票匹配比例分别计算，仅归入匹配比例最高的一个板块；'
                                            '同比例优先更细分的板块。' + primary['classification_basis'])
    return [primary]


def board_for(fund, asset_category, as_of=None):
    """The explicit reference destination, or highest portfolio match."""
    return boards_for(fund, asset_category, as_of=as_of)[0]


@catalog_synchronized
def build_board_coverage(universe, codes, snapshot, quant, sections):
    """Count independently proven boards; uncollected holdings stay unassigned."""
    from research_selection import _classify, _family, _fresh, _date
    from research_holdings import verify_board, supported_board_ids
    supported = set(supported_board_ids())
    catalog_known = 'funds' in universe
    catalog = {f['code']: f for f in universe.get('funds', []) if isinstance(f, dict) and f.get('code')}
    evidence = {f['code']: f for f in snapshot.get('funds', []) if isinstance(f, dict) and f.get('code')}
    by_code = {**catalog, **{code: {**catalog.get(code, {}), **fund} for code, fund in evidence.items()}}
    screened, eligible, selected, valid = Counter(), Counter(), Counter(), Counter()
    matched, unknown, mismatch = Counter(), Counter(), Counter()
    families, exclusions = {}, {}
    def identities(fund, item=None):
        return boards_for(fund, _classify(fund, item or {})[0], as_of=snapshot.get('as_of'))
    for code in catalog:
        fund = by_code[code]
        for board in identities(fund):
            identity = board['id']
            screened[identity] += 1
            if fund.get('eligible'):
                eligible[identity] += 1
                families.setdefault(identity, set()).add(_family(fund))
            else:
                exclusions.setdefault(identity, Counter()).update(fund.get('exclusion_reasons', []))
    from research_universe import plan_research_codes
    research_plan = plan_research_codes(codes, list(by_code.values()), as_of=snapshot.get('as_of'))
    for identity, targets in research_plan['board_targets'].items():
        selected[identity] = len(targets)
    for item in {q['code']: q for q in quant if isinstance(q, dict) and q.get('code')}.values():
        fund = by_code.get(item['code'], {})
        if not _fresh(fund, item, _date(snapshot.get('as_of'))):
            continue
        for board in identities(fund, item):
            identity = board['id']
            valid[identity] += 1
            if board.get('requires_holdings_match'):
                match = board.get('board_match') or verify_board(fund, identity, as_of=snapshot.get('as_of'))
                status = match.get('status', 'unknown')
                (matched if status == 'matched' else mismatch if status == 'mismatch' else unknown)[identity] += 1
    displayed = {section['id']: section for section in sections}
    result = []
    for identity, board in list(BOARDS.items()):
        funds = displayed.get(identity, {}).get('funds', [])
        if funds:
            status = 'candidate' if any(f.get('role') == 'candidate' for f in funds) else 'observation'
            reason = '每只基金仅归入持仓匹配比例最高的一个板块；本板块按比例优先选取最多三只，观察不等于买入。'
        elif identity == 'holdings_unclassified':
            status, reason = 'holdings_pending', '继续采集并核验持仓；不使用基金名称分配板块。'
        elif board.get('requires_holdings_match') and identity not in supported:
            status, reason = 'source_unavailable', '该方向需要的专属证据源尚未接入，不能以基金名称代替板块归属。'
        elif not catalog_known:
            status, reason = 'unknown', '旧报告未保存持仓归类后的全目录计数，等待新扫描。'
        elif not screened[identity]:
            status, reason = 'no_match', '已采集持仓中尚无通过该板块独立核验的基金；尚未采集的基金不能按名称计入，也不代表市场没有此类基金。'
        elif not eligible[identity]:
            status, reason = 'excluded', '持仓匹配的基金未通过产品初筛，继续寻找其他合格样本。'
        elif not selected[identity] and not funds:
            status, reason = 'not_researched', '已发现持仓匹配样本，等待在每板块三只及全局预算内深研。'
        else:
            status, reason = 'insufficient', '持仓方向已确认，净值历史、新鲜度或风险研究条件尚不足。'
        result.append({**board, 'catalog_counts_known': catalog_known,
            'screened_count': screened[identity] if catalog_known else None,
            'eligible_count': eligible[identity] if catalog_known else None,
            'eligible_family_count': len(families.get(identity, set())),
            'deep_count': selected[identity], 'valid_quant_count': valid[identity], 'displayed_count': len(funds),
            'matched_holdings_count': matched[identity], 'holdings_unknown_count': unknown[identity],
            'holdings_mismatch_count': mismatch[identity],
            'candidate_count': sum(f.get('role') == 'candidate' for f in funds), 'status': status, 'reason': reason,
            'classification_method': 'disclosed_holdings',
            'exclusion_reasons': [{'reason': key, 'count': value} for key, value in exclusions.get(identity, Counter()).most_common(3)]})
    return enrich_board_diagnostics(result, snapshot, quant, researched_codes=set(codes) | set(evidence))


def _gap_text(value, limit=240):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip('，；、 ') + '…'


def enrich_board_diagnostics(coverage, snapshot, quant, researched_codes=None):
    """Return detached gap explanations, preserving all saved coverage counts.

    Snapshot funds/quant rows are evidence of a deep-research attempt, including
    failed collection placeholders. Catalog-only rows never become examples.
    ``researched_codes`` additionally limits examples on a newly built report;
    old reports can use their saved snapshot without discarding catalog counts.
    """
    from research_selection import _classify, _fresh, _date
    from research_holdings import supported_board_ids, verify_board

    result = copy.deepcopy(coverage)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    snapshot_funds = {row['code']: row for row in snapshot.get('funds', [])
                      if isinstance(row, dict) and row.get('code')}
    quant_rows = {row['code']: row for row in quant
                  if isinstance(row, dict) and row.get('code')}
    allowed = set(researched_codes) if researched_codes is not None else set(snapshot_funds) | set(quant_rows)
    examples = {}
    reference_day = _date(snapshot.get('as_of'))
    for code in dict.fromkeys(list(snapshot_funds) + list(quant_rows)):
        if code not in allowed:
            continue
        fund, item = snapshot_funds.get(code, {}), quant_rows.get(code, {})
        if not fund and not item:
            continue
        details = {**item, **fund, 'code': code}
        for board in boards_for(details, _classify(details, item)[0], as_of=snapshot.get('as_of')):
            identity = board['id']
            quality = item.get('quality') or 'missing'
            fresh = _fresh(fund, item, reference_day)
            nav_date = item.get('nav_date') or fund.get('nav_date')
            match_status, match_reason = 'not_checked', ''
            if fresh and board.get('requires_holdings_match'):
                match = verify_board(fund, identity, as_of=snapshot.get('as_of'))
                match_status = match.get('status', 'unknown')
                match_reason = match.get('reason') or ''
            elif fresh:
                match_status = 'not_required'
            notes = item.get('reasons')
            notes = [_gap_text(note, 150) for note in notes if isinstance(note, str) and note.strip()] if isinstance(notes, list) else []
            if not item:
                reason = '已尝试深研，本轮未返回该基金的量化结果；不能以名称或初筛区间收益代替。'
            elif not fresh:
                if quality == 'ok':
                    quality = 'stale' if nav_date else 'missing'
                reason = ('净值日期或研究时点未通过新鲜度核验；' if item.get('quality') == 'ok' else '')
                reason += '；'.join(notes[:2]) or '净值历史、日期或有效日收益样本未满足量化研究条件。'
            elif board.get('requires_holdings_match') and match_status != 'matched':
                reason = match_reason or '净值量化已完成，但披露持仓与本板块的匹配仍未通过。'
            else:
                reason = '；'.join(notes[:2]) or '净值量化数据可用；是否形成候选仍取决于市场、风险及产品条件。'
            source_url = fund.get('source_url') or item.get('source_url')
            if not isinstance(source_url, str) or not re.match(r'^https?://', source_url):
                source_url = f'https://fund.eastmoney.com/{code}.html' if re.fullmatch(r'\d{6}', str(code)) else ''
            example = {'name': _gap_text(fund.get('name') or item.get('name') or code, 100), 'code': code,
                       'nav_date': nav_date, 'quality': quality, 'holdings_status': match_status,
                       'reason': _gap_text(reason), 'source_url': source_url}
            # Failed attempts first make gaps concrete without hiding valid data.
            rank = (0 if not fresh else 1 if match_status in ('unknown', 'mismatch') else 2, str(code))
            examples.setdefault(identity, []).append((rank, example))

    for board in result:
        if not isinstance(board, dict):
            continue
        identity = board.get('id')
        if board.get('displayed_count', 0) or board.get('status') in ('candidate', 'observation'):
            board['research_gap'] = None
            continue
        counts = {key: board.get(key) for key in ('screened_count', 'eligible_count', 'deep_count',
                                                  'valid_quant_count', 'matched_holdings_count')}
        selected_examples = [item for _, item in sorted(examples.get(identity, []), key=lambda row: row[0])][:3]
        if not board.get('deep_count'):
            selected_examples = []
        status = board.get('status', 'unknown')
        automatic = True
        if identity == 'holdings_unclassified':
            category, label = 'holdings', '持仓采集与归类队列'
            summary = '这是尚未完成持仓归类的基金队列，不是缺失的投资板块。未采集、资料无效或没有方向覆盖大部分已披露股票的基金均在此等候核验。'
            next_step = '每轮独立轮换最多192只持仓预检；取得有效持仓后计算各板块比例，只归入最高匹配板块；缺少明确行业时按来源新增板块。'
        elif status == 'source_unavailable':
            category, label = 'holdings', '专属证据源尚未接入'
            summary = '该方向需要对应指数成分、风格、海外暴露或债券配置证据，当前接入的数据不足以验证；已归类为0不代表市场没有基金。'
            next_step = '接入可核验的对应证据后再归类；公开搜索仅用于发现基金，不能替代持仓或专属成分证据。'
            automatic = False
        elif status in ('holdings_pending', 'holdings_mismatch'):
            category = 'holdings'
            unavailable = bool(board.get('requires_holdings_match') and identity not in supported_board_ids())
            if unavailable:
                label = '专属证据尚未接入'
                summary = '净值量化已有结果，但对应指数成分、组合风格、海外暴露、久期或资产配置证据尚未接入，不能确认本板块。'
                next_step = '系统可继续更新已接入的净值、行情和公告；该方向需要接入并核验专属证据后才能形成结论，不能承诺下一轮补齐。'
                automatic = False
            elif status == 'holdings_mismatch':
                label = '持仓与板块不匹配'
                summary = f'本轮 {board.get("holdings_mismatch_count", 0)} 只量化可用基金的披露持仓未达到本板块匹配规则，不用相似名称补推荐。'
                next_step = '下一轮继续扫描公开排行，并在现有轮询预算内优先研究未形成结论方向的其他合格样本；有新披露时重新核验。'
            else:
                label = '持仓证据待核验'
                summary = '净值量化已有结果，但持仓报告期、股票身份、权重或明确主题标签不足，暂不能确认板块归属。'
                next_step = '下一轮继续尝试已接入的公开持仓披露及股票标签，并在有其他合格样本时轮换研究；ETF穿透和未接入市场证据仍可能缺失。'
        elif status == 'excluded':
            category, label = 'screening', '未通过初筛'
            reasons = board.get('exclusion_reasons') or []
            reason_text = '；'.join(_gap_text(row.get('reason'), 100) for row in reasons[:3] if isinstance(row, dict) and row.get('reason'))
            summary = f'识别到 {board.get("screened_count", 0)} 只该方向基金，本轮没有通过初筛的样本。' + reason_text
            next_step = '下一轮公开排行更新后重新检查净值日期、基金类型和已接入的产品限制；限制未解除前不补位。'
        elif status == 'not_researched':
            category, label = 'not_researched', '等待深研覆盖'
            summary = f'已有 {board.get("eligible_count", 0)} 只通过初筛的样本，本轮深研预算尚未覆盖此方向，未形成结论。'
            next_step = '后续轮次在全局预算和每板块最多三只的范围内继续轮询合格样本，避免长期只研究热门方向；不保证下一轮一定覆盖。'
        elif status == 'no_match':
            category, label = 'no_match', '尚无基金优先归入此方向'
            summary = '已采集持仓中尚无基金以此方向作为最高匹配板块；同一基金可能已优先进入比例更高或更细分的方向。未采集部分继续轮换，不代表市场没有相应基金。'
            next_step = '下一轮继续扫描已接入的公开基金目录和排行；持仓未采集或专属证据尚未接入的产品，仍需继续核验。'
        elif status == 'unknown' or board.get('catalog_counts_known') is False:
            category, label = 'insufficient', '初筛记录待更新'
            summary = '这份报告未保存该方向的完整初筛覆盖计数，无法据此判断有无合格样本；保留已知研究记录。'
            next_step = '下一轮公开目录扫描后补充新的覆盖记录；旧报告缺失的计数保持未知。'
        else:
            stale = any(item['quality'] == 'stale' for item in selected_examples)
            if stale:
                category, label = 'stale_data', '净值数据已过期'
                summary = '本轮已尝试深研，但示例基金净值日期未通过新鲜度核验，历史指标不能充当当前决策。'
                next_step = '下一轮更新已接入的净值与日收益，重新核验日期和连续样本；源站尚未披露新净值时继续保留空缺。'
            else:
                category, label = 'insufficient', '研究数据或条件不足'
                if board.get('valid_quant_count'):
                    summary = '本轮已有部分可用量化数据，仍未形成可展示的基金结论；不能把历史研究分当成新增条件已满足。'
                else:
                    summary = '本轮已尝试深研，净值历史、有效日收益或其他研究条件仍不足，未形成可展示结论。'
                next_step = '下一轮继续采集已接入的净值、行情和公告并重新计算；有替代合格样本时轮换研究，数据仍不足则保持待核验。'
        board['research_gap'] = {'category': category, 'label': label, 'summary': summary,
                                 'next_step': next_step, 'automatic': automatic,
                                 'counts': counts, 'examples': selected_examples}
    return result
