"""Dated publisher memberships and explicitly limited public-business samples.

The latter are a verified small research pool, not official index members or a
complete industry universe. Observation dates never replace publication dates.
"""
from __future__ import annotations

import copy
import html
import io
import json
import math
import re
import urllib.request
from urllib.parse import urlencode
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

from research_data import CHINA, now_iso
from research_sample_policy import SELECTION_METHOD

CNI_BASE = 'https://www.cnindex.com.cn/'
CNI_REFERENCES = {
    'sector_ai_application': {'code': '980112', 'title': '国证AI应用指数', 'aliases': ['国证AI应用指数', 'AI应用']},
    'style_microcap': {
        'code': '399317', 'title': '国证A股指数', 'aliases': ['国证A指'],
        'selection_order': 'smallest_market_cap', 'requires_complete_universe': True,
        'minimum_universe_size': 4000,
        'selection_scope': '在国证A股指数完整当前有效成分范围按同批有效总市值由小到大选样；不是官方微盘指数成分。'},
    'sector_memory_chip': {'code': '980138', 'title': '国证存储芯片产业指数', 'aliases': ['存储芯片']},
    'sector_solid_state_battery': {'code': '980140', 'title': '国证固态电池指数', 'aliases': ['固态电池']},
}
CSI_REFERENCES = {
    'sector_commercial_aerospace': {
        'code': '932720', 'title': '中证商业航天主题指数',
        'aliases': ['中证商业航天主题指数', '商业航天']},
}
BUSINESS_REFERENCES = {
    'sector_auto_vehicle': {'code': 'business:auto_vehicle', 'title': '汽车整车 · 公开整车制造业务核验样本池'},
    'sector_diversified_finance': {'code': 'business:diversified_finance', 'title': '多元金融 · 金融控股及租赁有限样本池'},
    'sector_domestic_computing': {'code': 'business:domestic_computing', 'title': '国产算力 · 公开业务核验样本池'},
    'sector_nuclear_fusion': {'code': 'business:nuclear_fusion', 'title': '可控核聚变 · 公开业务核验样本池'},
    'sector_cpo': {'code': 'business:cpo', 'title': 'CPO · 公开业务核验样本池'},
    'sector_pcb': {'code': 'business:pcb', 'title': 'PCB · 公开业务核验样本池'},
    'sector_mlcc': {'code': 'business:mlcc', 'title': 'MLCC · 公开业务核验样本池'},
    'sector_compute_leasing': {'code': 'business:compute_leasing', 'title': '算力租赁 · 公开业务核验样本池'},
    'sector_rare_earth_magnet': {'code': 'business:rare_earth_magnet', 'title': '稀土永磁 · 公开业务核验样本池'},
    'sector_manufacturing': {'code': 'business:manufacturing', 'title': '机械与高端制造 · 工程机械及液压有限样本池'},
    'sector_lithium_mining': {'code': 'business:lithium_mining', 'title': '锂矿 · 公开资源业务核验样本池'},
    'sector_agriculture': {'code': 'business:agriculture', 'title': '农林牧渔 · 种业饲料及养殖有限样本池'},
    'sector_oil_gas': {'code': 'business:oil_gas', 'title': '油气资源 · 公开勘探开发业务核验样本池'},
    'gold': {'code': 'business:gold_mining_equity', 'title': '黄金矿业股票 · 公开采矿业务核验样本池'},
    'commodities': {'code': 'business:resource_equity', 'title': '大宗商品·资源企业股票 · 金属采矿及油气有限样本池'},
    'sector_brain_computer': {'code': 'business:brain_computer', 'title': '脑机接口 · 设备及临床研究关联有限样本池'},
    'sector_insurance': {'code': 'business:insurance', 'title': '保险 · 公开保险业务核验样本池'},
}
BUSINESS_EVIDENCE = {
    'sector_auto_vehicle': [
        {'ts_code': '600104.SH', 'name': '上汽集团',
         'url': 'https://www.saicmotor.com/m/gsgk/gsjs/index.shtml', 'title': '上汽集团官网 · 公司介绍',
         'published_date': None, 'required': ['上海汽车集团股份有限公司', '600104', '以整车业务为龙头', '13个整车基地'],
         'description': '上市公司官网披露整车业务及整车制造基地；不以单纯零部件、经销商代替整车制造样本。'},
        {'ts_code': '601238.SH', 'name': '广汽集团',
         'url': 'https://www.gacgroup.com/cn/about', 'title': '广汽集团官网 · 公司总览',
         'published_date': None, 'required': ['广州汽车集团股份有限公司', '601238.SH', '主营业务涵盖研发、整车'],
         'description': '上市公司官网披露整车研发与制造业务，兼营零部件和服务；不推定整车业务收入占比。'},
        {'ts_code': '601633.SH', 'name': '长城汽车',
         'url': 'https://www.gwm.com.cn/aboutUs.html', 'title': '长城汽车官网 · 走进长城',
         'published_date': None, 'required': ['长城汽车是一家全球化智能科技公司', '业务包括整车', '零部件设计、研发、生产、销售与服务'],
         'description': '上市公司官网披露整车设计、研发、生产及销售业务与旗下汽车品牌；不以整车零部件供应商替代整车厂。'},
    ],
    'sector_diversified_finance': [
        {'ts_code': '000987.SZ', 'name': '越秀资本',
         'url': 'https://www.yuexiu-finance.com/capital/gongsijianjie.html', 'title': '越秀资本官网 · 公司简介',
         'published_date': None, 'required': ['广州越秀资本控股集团股份有限公司', '000987.SZ', '多元金融上市平台', '融资租赁、不良资产管理、投资管理'],
         'description': '上市公司官网披露融资租赁、不良资产管理及投资管理等多元金融业务；区别于银行或纯证券经纪样本。'},
        {'ts_code': '600390.SH', 'name': '五矿资本',
         'url': 'https://www.minmetals-finance.com/introduction.html', 'title': '五矿资本官网 · 企业简介',
         'published_date': None, 'required': ['五矿资本股份有限公司', 'A股市场上稀缺的全牌照金融控股公司', '投资、信托、金融租赁'],
         'description': '上市公司官网披露信托、金融租赁等金融控股业务；以金融集团合并财务分析，不推定各牌照收入占比。'},
        {'ts_code': '000415.SZ', 'name': '渤海租赁',
         'url': 'http://www.bohaileasing.com/', 'title': '渤海租赁官网 · 公司与租赁业务',
         'published_date': None, 'required': ['渤海租赁股份有限公司', '中国A股深交所主板上市的大型租赁产业集团', '飞机租赁和租赁资产管理服务'],
         'description': '上市公司官网披露租赁集团身份及飞机租赁、租赁资产管理业务；与金控形成有限多元金融池，非全行业覆盖。'},
    ],
    'sector_domestic_computing': [
        {'ts_code': '688256.SH', 'name': '寒武纪',
         'url': 'https://www.cambricon.com/index.php?m=content&c=index&a=lists&catid=7',
         'title': '寒武纪官网 · 公司介绍', 'published_date': None,
         'required': ['寒武纪成立于2016年', '人工智能芯片产品', '提供充裕算力'],
         'description': '公司官网披露人工智能核心处理器芯片、云边端智能芯片及服务器场景算力业务。'},
        {'ts_code': '688047.SH', 'name': '龙芯中科',
         'url': 'https://loongson.cn/index.php/application/list?id=3',
         'title': '龙芯中科官网 · 服务器产品', 'published_date': None,
         'required': ['688047', '龙芯3C6000系列服务器处理器芯片', '完全自主的龙架构'],
         'description': '公司官网披露自主龙架构服务器CPU及计算、推理和训练服务器应用。'},
        {'ts_code': '603019.SH', 'name': '中科曙光',
         'url': 'https://www.sugon.com/about/index', 'title': '中科曙光官网 · 公司概况',
         'published_date': None, 'required': ['603019', '曙光信息产业股份有限公司', '高端计算', '智能计算'],
         'description': '上市公司官网披露高端计算、智能计算及服务器产品；不据此将全部产品认定为自主芯片。'},
    ],
    'sector_nuclear_fusion': [
        {'ts_code': '600875.SH', 'name': '东方电气',
         'url': 'https://www.dec-ltd.cn/info/1523/13005.htm',
         'title': '东方电气股份官网 · 2026中国国际核工业展览会',
         'published_date': '2026-04-23',
         'required': ['东方电气股份有限公司', '可控核聚变中国', '主机线圈', 'ITER项目包层屏蔽模块', '2026-04-23'],
         'description': '公司官网披露环流三号主机线圈及ITER包层屏蔽模块装备；不代表核聚变收入占比。'},
        {'ts_code': '601727.SH', 'name': '上海电气',
         'url': 'https://www.gzw.sh.gov.cn/shgzw_zxzx_gqdt/20260814/67baeb6d5610423b90eeb0f3039f7cd3.html',
         'title': '上海市国资委 · 上海电气BEST核心设备进展',
         'published_date': '2026-08-14',
         'required': ['上海电气下属核电集团承接', '紧凑型聚变能实验装置', '真空室', '中部冷屏', '2026-08-14'],
         'description': '市国资委披露上海电气下属核电集团承接BEST真空室与中部冷屏；不代表核聚变收入占比。'},
        {'ts_code': '000969.SZ', 'name': '安泰科技',
         'url': 'http://www.atmcn.com/mtzx/gsxw/2026/0327/5020.html', 'title': '安泰科技官网 · 聚变包层装备技术',
         'published_date': '2026-03-27', 'required': ['安泰科技股份有限公司', '000969', '包层用钨铜零件、包层第一壁、双壁管和包层模块', '2026-03-27'],
         'description': '上市公司官网披露已研制的核聚变包层零件、第一壁及模块；联合实验室和装备业务不等同核聚变收入占比。'},
    ],
    'sector_cpo': [
        {'ts_code': '300394.SZ', 'name': '天孚通信',
         'url': 'https://www.tfcsz.com/news/974.html', 'title': '天孚通信官网 · OFC2025光引擎产品',
         'published_date': '2025-04-10',
         'required': ['300394', '天孚通信', '共封装光学（CPO）', 'FAU', 'POSA', '2025-04-10'],
         'description': '公司官网披露面向CPO的FAU、POSA产品及相关封装方案；不代表CPO收入占比。'},
        {'ts_code': '002281.SZ', 'name': '光迅科技',
         'url': 'https://www.accelink.com/en/lighting_your_dreams/1968138961071140866.html',
         'title': '光迅科技官网 · CIOE2025 CPO技术方案', 'published_date': '2025-09-17',
         'required': ['Accelink', 'New-Generation CPO (Co-Packaged Optical)', 'CPO technology', '2025-09-17'],
         'description': '公司官网披露CPO光互连技术解决方案；研发/技术展示不等同规模收入。'},
        {'ts_code': '688313.SH', 'name': '仕佳光子',
         'url': 'https://www.sjphotons.com.cn/about/exhibitiondetail/23', 'title': '仕佳光子官网 · OFC2025硅光CPO光源',
         'published_date': None, 'required': ['仕佳光子', '硅光 CPO', '高功率 CW 激光器芯片', '2025'],
         'description': '公司官网披露展出的硅光CPO用高功率CW激光器芯片；产品展示不等同CPO规模收入。'},
        {'ts_code': '000988.SZ', 'name': '华工科技',
         'url': 'https://www.hgtech.com.cn/gsxw/4269.jhtml', 'title': '华工科技官网 · 华工正源CPO光引擎',
         'published_date': '2025-09-12', 'required': ['华工科技', '子公司华工正源', 'CPO光引擎', '2025-09-12'],
         'description': '公司官网披露子公司华工正源的CPO光引擎研发与实时展示；不推定上市公司CPO收入占比。'},
    ],
    'sector_pcb': [
        {'ts_code': '002916.SZ', 'name': '深南电路',
         'url': 'https://www.scc.com.cn/scc/cpjs/PCB/index.html', 'title': '深南电路官网 · PCB产品技术',
         'published_date': None, 'required': ['深南电路股份有限公司', '印制电路板（PCB）', 'HDI埋盲孔结构'],
         'description': '公司官网披露印制电路板及HDI结构产品技术；不据此推定主营市占率。'},
        {'ts_code': '300476.SZ', 'name': '胜宏科技',
         'url': 'https://www.shpcb.com/index.html', 'title': '胜宏科技官网 · 产品领域',
         'published_date': None, 'required': ['胜宏科技专业从事高阶HDI、高多层PCB的研发、生产和销售', 'AI算力卡', '服务器'],
         'description': '公司官网披露高阶HDI及高多层PCB研发生产销售和AI服务器应用。'},
        {'ts_code': '002463.SZ', 'name': '沪电股份',
         'url': 'https://www.wustec.com/about.php', 'title': '沪士电子官网 · 公司概况',
         'published_date': None, 'required': ['沪士电子股份有限公司', '002463', '印制电路板的研发设计和生产制造'],
         'description': '上市公司官网披露印制电路板研发设计和生产制造及封装载板业务；不推定主营市占率。'},
        {'ts_code': '603228.SH', 'name': '景旺电子',
         'url': 'https://www.kinwong.com/', 'title': '景旺电子官网 · PCB产品与证券身份',
         'published_date': None, 'required': ['603228', '深圳市景旺电子股份有限公司', '全球领先的印制电路板制造商', '高密度互连板'],
         'description': '上市公司官网披露PCB制造、柔性电路板、高密度互连板及高多层电路板产品。'},
        {'ts_code': '688183.SH', 'name': '生益电子',
         'url': 'https://www.sye.com.cn/gywm/index.aspx', 'title': '生益电子官网 · 公司简介',
         'published_date': None, 'required': ['688183', '生益电子股份有限公司', '专业制作高精度、高密度、高品质印制电路板'],
         'description': '上市公司官网披露印制电路板制造业务；主体为生益电子，区别于覆铜板企业生益科技。'},
        {'ts_code': '002436.SZ', 'name': '兴森科技',
         'url': 'https://www.chinafastprint.com/about', 'title': '兴森科技官网 · 公司介绍与PCB业务',
         'published_date': None, 'required': ['深圳市兴森快捷电路科技股份有限公司', '002436', 'PCB样板数字化工厂运行', 'PCB设计>制造>贴装'],
         'description': '上市公司官网披露PCB设计、制造、贴装与样板数字化工厂；不以覆铜板材料业务替代PCB制造。'},
    ],
    'sector_mlcc': [
        {'ts_code': '000636.SZ', 'name': '风华高科',
         'url': 'https://www.fhcomp.com/zh-cn/product_page/?code=010000', 'title': '风华高科官网 · MLCC电容产品',
         'published_date': None, 'required': ['风华高科', 'MLCC', '电容产品服务'],
         'description': '公司官网产品目录列示MLCC多层陶瓷电容器。'},
        {'ts_code': '300408.SZ', 'name': '三环集团',
         'url': 'https://www.cctc.cc/product/product/frontList',
         'request_data': {'level': '2', 'id': '46'}, 'response_kind': 'cctc_product',
         'display_url': 'https://www.cctc.cc/productSecMlcc.html',
         'title': '三环集团官网 · 多层片式陶瓷电容器公开产品目录',
         'published_date': None, 'required': ['多层片式陶瓷电容器', 'Multilayer Ceramic Chip Capacitor', 'MLCC'],
         'description': '公司官网公开产品目录第46项披露多层片式陶瓷电容器及MLCC系列。'},
        {'ts_code': '603678.SH', 'name': '火炬电子',
         'url': 'http://www.torch.cn/research.php', 'title': '火炬电子官网 · 多层陶瓷电容器研发与产品',
         'published_date': None, 'required': ['603678', '火炬牌多层陶瓷固定电容器', 'MLCC'],
         'description': '公司官网披露火炬牌多层陶瓷固定电容器产品和MLCC研发；不将单层电容或上游粉体材料替代MLCC。'},
    ],
    'sector_compute_leasing': [
        {'ts_code': '688158.SH', 'name': '优刻得',
         'url': 'https://www.ucloud.cn/site/product/gpu.html', 'title': '优刻得官网 · GPU云服务器',
         'published_date': None, 'required': ['688158', 'GPU云服务器', '按时 / 包月 / 包年', '长租续费'],
         'description': '公司官网披露GPU云计算资源按时/包月/包年付费与长租服务。'},
        {'ts_code': '688316.SH', 'name': '青云科技',
         'url': 'https://www.qingcloud.com/products/ai-computing-service/', 'title': '青云科技官网 · AI算力云',
         'published_date': None, 'required': ['688316', 'AI 算力云', '弹性按需计费和整租两种租赁形式'],
         'description': '公司官网披露GPU算力云弹性按需计费与整租两种租赁形式。'},
        {'ts_code': '920493.BJ', 'name': '并行科技',
         'url': 'https://www.paratera.com/', 'title': '并行科技官网 · 算力资源与按需付费',
         'published_date': None, 'required': ['北京并行科技股份有限公司', '920493', 'GPU云服务器', '按需付费'],
         'description': '上市公司官网披露GPU及超算云资源按需付费服务；使用现行北交所代码920493，非原代码839493。'},
    ],
    'sector_rare_earth_magnet': [
        {'ts_code': '300748.SZ', 'name': '金力永磁',
         'url': 'https://cn.jlmag-innovation.com/', 'title': '金力永磁全资销售子公司官网 · 钕铁硼磁材',
         'published_date': None, 'required': ['金力永磁', '高性能钕铁硼磁材制造商', 'SZ300748', '100%控股的全资子公司'],
         'description': '金力永磁全资销售子公司披露母公司高性能钕铁硼磁材业务及上市代码。'},
        {'ts_code': '600366.SH', 'name': '宁波韵升',
         'url': 'https://www.yunsheng.com/product.html', 'title': '宁波韵升官网 · 钕铁硼产品',
         'published_date': None, 'required': ['宁波韵升股份有限公司', '600366', '烧结钕铁硼', '粘结钕铁硼'],
         'description': '公司官网披露烧结及粘结钕铁硼磁材产品；不以稀土开采公司替代永磁样本。'},
        {'ts_code': '000970.SZ', 'name': '中科三环',
         'url': 'https://www.san-huan.com.cn/About/Company', 'title': '中科三环官网 · 公司简介',
         'published_date': None, 'required': ['北京中科三环高技术股份有限公司', '000970', '烧结钕铁硼永磁体生产企业', '粘结钕铁硼永磁体生产企业'],
         'description': '上市公司官网披露旗下烧结及粘结钕铁硼永磁体制造企业；不以单纯稀土开采替代永磁业务。'},
    ],
    'sector_manufacturing': [
        {'ts_code': '600031.SH', 'name': '三一重工',
         'url': 'https://www.sany.com.cn/', 'title': '三一重工官网 · 工程机械产品',
         'published_date': None, 'required': ['600031', '三一重工', '液压挖掘机'],
         'description': '上市公司官网披露液压挖掘机等工程机械产品及证券代码；仅代表工程机械制造子领域。'},
        {'ts_code': '601100.SH', 'name': '恒立液压',
         'url': 'https://www.henglihydraulics.com/col42/index', 'title': '恒立液压官网 · 公司简介',
         'published_date': None, 'required': ['601100', '恒立液压', '液压元件', '液压系统'],
         'description': '上市公司官网披露液压元件、精密铸件及液压系统制造；有限工程机械及液压样本不构成整个高端制造行业。'},
        {'ts_code': '000425.SZ', 'name': '徐工机械',
         'url': 'https://www.xcmg.com/', 'title': '徐工机械官网 · 工程机械产品与上市身份',
         'published_date': None, 'required': ['徐工集团工程机械股份有限公司', '000425.SZ', '起重机械', '挖掘机械'],
         'description': '上市公司官网披露起重、挖掘等工程机械产品；仅代表工程机械制造子领域。'},
        {'ts_code': '000157.SZ', 'name': '中联重科',
         'url': 'https://www.zoomlion.com/', 'title': '中联重科官网 · 工程机械产品',
         'published_date': None, 'required': ['中联重科股份有限公司', '工程机械', '混凝土机械', '工程起重机械'],
         'description': '上市公司官网披露混凝土机械、工程起重机械等产品；仅代表工程机械制造子领域。'},
    ],
    'sector_lithium_mining': [
        {'ts_code': '002460.SZ', 'name': '赣锋锂业',
         'url': 'https://www.ganfenglithium.com/', 'title': '赣锋锂业官网 · 上游锂资源开发',
         'published_date': None, 'required': ['002460', '上游锂资源开发', '锂矿资源遍布'],
         'description': '上市公司官网披露上游锂资源开发及全球锂矿资源；采矿、加工和电池业务并存，不推定锂矿收入占比。'},
        {'ts_code': '002466.SZ', 'name': '天齐锂业',
         'url': 'https://www.tianqilithium.com/', 'title': '天齐锂业官网 · 锂资源业务与发展历程',
         'published_date': None, 'required': ['002466', '天齐锂业', '锂辉石矿开采权', '收购泰利森锂业'],
         'description': '上市公司官网披露锂辉石矿开采权及泰利森锂业权益；不以电池制造商替代锂资源样本。'},
        {'ts_code': '002738.SZ', 'name': '中矿资源',
         'url': 'https://www.sinomine.cn/', 'title': '中矿资源官网 · 锂矿与锂盐业务',
         'published_date': None, 'required': ['中矿资源集团股份有限公司', '锂矿的开采', '锂盐的研发、生产和销售'],
         'description': '上市公司官网披露锂矿开采及锂盐研发生产销售；采矿与加工业务并存，不推定锂矿收入占比。'},
    ],
    'sector_agriculture': [
        {'ts_code': '300498.SZ', 'name': '温氏股份',
         'url': 'https://www.wens.com.cn/IntroductionGroup/index.aspx', 'title': '温氏股份官网 · 集团简介',
         'published_date': None, 'required': ['300498', '温氏食品集团股份有限公司', '以畜禽养殖为主业'],
         'description': '上市公司官网披露以畜禽养殖为主业的农牧业务及养猪、养鸡产业链。'},
        {'ts_code': '000876.SZ', 'name': '新希望',
         'url': 'https://www.newhopeliuhe.com/lh/briefintroduction.html', 'title': '新希望六和官网 · 公司介绍',
         'published_date': None, 'required': ['000876', '新希望六和股份有限公司', '饲料', '生猪养殖'],
         'description': '上市公司官网披露饲料和生猪养殖业务；与温氏、隆平组成有限农牧种业样本，不代表林业渔业全覆盖。'},
        {'ts_code': '000998.SZ', 'name': '隆平高科',
         'url': 'https://www.lpht.com.cn/', 'title': '隆平高科官网 · 种业与产品',
         'published_date': None, 'required': ['隆平高科', '种子', '水稻'],
         'description': '公司官网披露水稻等农作物种子产品；只代表种业关联，不推定农林牧渔全行业排名。'},
    ],
    'sector_oil_gas': [
        {'ts_code': '600938.SH', 'name': '中国海油',
         'url': 'https://www.cnoocltd.com/gywm/cjwt/', 'title': '中国海油上市公司官网 · 经营范围与证券身份',
         'published_date': None, 'required': ['600938', '中国海洋石油有限公司', '勘探、开发、生产及销售原油和天然气'],
         'description': '上市公司官网明确A股代码及原油天然气勘探、开发、生产和销售业务，区分上市公司与母集团。'},
        {'ts_code': '603619.SH', 'name': '中曼石油',
         'url': 'https://www.zpec.com/business/oilAndGasExplorationAndDevelopment', 'title': '中曼石油官网 · 油气勘探开发',
         'published_date': None, 'required': ['603619', '中曼', '油气勘探开发', '油气开采许可证'],
         'description': '上市公司官网披露自有勘探开发及油气开采许可；同时存在工程服务业务，不推定资源业务收入占比。'},
    ],
    'gold': [
        {'ts_code': '601899.SH', 'name': '紫金矿业',
         'url': 'https://www.zijinmining.com/about/about_us.htm', 'title': '紫金矿业官网 · 矿业业务及上市身份',
         'published_date': None, 'required': ['Zijin Mining Group', '601899', 'gold', 'exploration'],
         'description': '上市公司官网披露黄金等金属勘查及开发；同时经营铜等金属，不能将其股价当作黄金现货价格。'},
        {'ts_code': '600547.SH', 'name': '山东黄金',
         'url': 'https://www.sdhjgf.com.cn/', 'title': '山东黄金上市公司官网 · 黄金矿业',
         'published_date': None, 'required': ['山东黄金矿业股份有限公司', '600547', '黄金产量', '生态矿业'],
         'description': '山东黄金矿业上市公司官网披露黄金生产与生态矿业；采用A股公司行情和财务，不是商品金价指标。'},
        {'ts_code': '600988.SH', 'name': '赤峰黄金',
         'url': 'https://www.cfgold.com/', 'title': '赤峰黄金官网 · 黄金采选与销售业务',
         'published_date': None, 'required': ['赤峰吉隆黄金矿业', '黄金生产商', '主要在全球范围内从事黄金的采、选和销售业务'],
         'description': '上市公司官网披露黄金采选及销售业务；采用矿业公司股价及财务，不等同黄金现货价格。'},
    ],
    'commodities': [
        {'ts_code': '601899.SH', 'name': '紫金矿业',
         'url': 'https://www.zijinmining.com/about/about_us.htm', 'title': '紫金矿业官网 · 金属资源业务及上市身份',
         'published_date': None, 'required': ['Zijin Mining Group', '601899', 'gold', 'exploration'],
         'description': '上市公司官网披露金属勘查与开发业务；使用公司整体财务及A股股价，不作为金属现货或期货价格。'},
        {'ts_code': '600938.SH', 'name': '中国海油',
         'url': 'https://www.cnoocltd.com/gywm/cjwt/', 'title': '中国海油上市公司官网 · 油气资源业务及证券身份',
         'published_date': None, 'required': ['600938', '中国海洋石油有限公司', '勘探、开发、生产及销售原油和天然气'],
         'description': '上市公司官网披露原油天然气勘探、开发、生产和销售；资源企业股票池不代表全品种商品现货或期货市场。'},
    ],
    'sector_brain_computer': [
        {'ts_code': '688626.SH', 'name': '翔宇医疗',
         'url': 'https://www.xyyl.com/news_details/987.html', 'title': '翔宇医疗官网 · 脑机接口数据集与临床研究合作',
         'published_date': None, 'required': ['翔宇医疗', '脑机接口高质量数据集', '联盟首批成员'],
         'description': '公司官网披露脑机接口数据集及临床研究合作；包含拟于2027年建成的项目，不据此认定现有规模收入或成熟产品。',
         'role': '脑机接口设备与研究关联样本（有限池，非主题收入或主营龙头认证）'},
        {'ts_code': '301293.SZ', 'name': '三博脑科',
         'url': 'https://www.sbnk.cn/xinwen/xinwen/20250401_14539.html', 'title': '三博脑科医院官网 · 脑机接口实验室及临床应用平台',
         'published_date': '2025-04-01', 'required': ['三博脑科', '脑机接口北京市重点实验室', '临床应用场景平台', '2025-04-01'],
         'description': '上市公司旗下三博脑科医院披露共建实验室及临床应用平台；属临床研究关联，非上市公司脑机接口产品收入证明。',
         'role': '脑机接口临床研究关联样本（有限池，非主题收入或主营龙头认证）'},
        {'ts_code': '002925.SZ', 'name': '盈趣科技',
         'url': 'https://www.intretech.com.cn/Ne_d_gci_19_id_239.html', 'title': '盈趣科技官网 · 脑机接口实训及脑电设备',
         'published_date': '2025-06-12', 'required': ['盈趣科技', '脑机接口实训本科学分课程', 'Xmuse便携式脑电波仪', '2025-06-12'],
         'description': '上市公司官网披露脑机接口课程合作及便携式脑电设备；教学与研究关联不证明规模收入或成熟医疗产品。',
         'role': '脑机接口设备及教学研究关联样本（有限池，非主题收入或主营龙头认证）'},
    ],
    'sector_insurance': [
        {'ts_code': '601601.SH', 'name': '中国太保',
         'url': 'https://www.cpic.com.cn/aboutUs/zgtbgk/jtjj/', 'title': '中国太保官网 · 集团简介',
         'published_date': None,
         'required': ['中国太平洋保险（集团）股份有限公司', '国内领先的综合性保险集团',
                      '人寿保险、财产保险、养老保险、健康保险、农业保险和资产管理'],
         'description': '上市保险集团官网披露各类保险业务与集团身份；与人保构成有限样本池，不宣称整个保险行业排名。'},
        {'ts_code': '601319.SH', 'name': '中国人保',
         'url': 'https://www.picc.com/gyrb/jtjs/', 'title': '中国人保官网 · 集团介绍',
         'published_date': None,
         'required': ['中国人民保险集团股份有限公司', '业务范围覆盖财产险、人身险、再保险',
                      '上海证券交易所登陆A股市场'],
         'description': '上市保险集团官网披露财产险、人身险及再保险业务；不以参股保险的非保险公司代替样本。'},
        {'ts_code': '601628.SH', 'name': '中国人寿',
         'url': 'https://www.e-chinalife.com/xxpl/gywm/gsjs/', 'title': '中国人寿保险官网 · 公司简介',
         'published_date': '2026-09-22', 'required': ['中国人寿保险股份有限公司', '国内寿险行业', '2026-09-22'],
         'description': '上市公司官网披露寿险保险主体及业务；有限保险公司样本，不据此认定全行业龙头排名。'},
        {'ts_code': '601336.SH', 'name': '新华保险',
         'url': 'https://www.newchinalife.com/spage/cn/companyProfileAboutXH/index.html', 'title': '新华保险官网 · 公司概况',
         'published_date': None, 'required': ['新华人寿保险股份有限公司', '601336', '提供全面的寿险产品及服务'],
         'description': '上市公司官网披露A股身份及全面寿险产品与服务；不以参股保险的公司替代保险主体。'},
    ],
}
# Share exact company evidence across resource-equity directions without sharing
# mutable dictionaries. These remain mining/oil stocks, never futures prices.
for _sector, _codes in (
        ('gold', {'600547.SH', '600988.SH'}),
        ('sector_oil_gas', {'603619.SH'}),
        ('sector_lithium_mining', {'002460.SZ', '002466.SZ', '002738.SZ'})):
    BUSINESS_EVIDENCE['commodities'].extend(
        copy.deepcopy(row) for row in BUSINESS_EVIDENCE[_sector] if row['ts_code'] in _codes)
del _sector, _codes
# The CNI memory *industry* universe also contains wafer fabs and equipment.
# Keep only official members whose own current product pages independently
# confirm memory-chip/module business, rather than picking a large equipment
# company merely because it is in the broader industry-chain index.
CNI_BUSINESS_FILTERS = {
    'sector_memory_chip': [
        {'ts_code': '603986.SH', 'name': '兆易创新',
         'url': 'https://www.gigadevice.com.cn/product/flash',
         'title': '兆易创新官网 · 闪存产品', 'published_date': None,
         'required': ['兆易创新提供全面的Flash存储器产品组合', 'SPI NOR Flash', 'SPI NAND Flash'],
         'description': '公司官网披露NOR/NAND闪存芯片产品；同时核对国证存储芯片产业当前成员。'},
        {'ts_code': '688008.SH', 'name': '澜起科技',
         'url': 'https://www.montage-tech.com/cn/Memory_Interface',
         'title': '澜起科技官网 · 内存接口及配套芯片', 'published_date': None,
         'required': ['澜起科技', '内存接口及配套芯片', 'DDR5服务器端产品'],
         'description': '公司官网披露内存接口及配套芯片产品；同时核对国证存储芯片产业当前成员。'},
        {'ts_code': '301308.SZ', 'name': '江波龙',
         'url': 'https://cn.longsys.com/about/longsys/',
         'title': '江波龙官网 · 公司简介', 'published_date': None,
         'required': ['江波龙是一家全球领先的半导体存储品牌企业', '嵌入式存储', '内存条四大产品线'],
         'description': '公司官网披露半导体存储芯片/模组与内存条产品；同时核对国证存储芯片产业当前成员。'},
        {'ts_code': '688123.SH', 'name': '聚辰股份',
         'url': 'https://www.giantec-semi.com/', 'title': '聚辰半导体官网 · EEPROM及NOR Flash产品',
         'published_date': None, 'required': ['聚辰半导体股份有限公司', '688123.SH', 'EEPROM芯片', 'NOR Flash芯片'],
         'description': '公司官网披露EEPROM及NOR Flash芯片产品；同时核对国证存储芯片产业当前成员。'},
        {'ts_code': '688525.SH', 'name': '佰维存储',
         'url': 'https://www.biwin.com.cn/', 'title': '佰维存储官网 · 半导体存储器与嵌入式存储',
         'published_date': None, 'required': ['深圳佰维存储科技股份有限公司', '688525', '公司专注半导体存储器的研发设计、封测、生产和销售', '嵌入式存储'],
         'description': '公司官网披露半导体存储器及嵌入式存储、内存产品；同时核对国证存储芯片产业当前成员。'},
    ],
}


def _stamp(value):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return stamp.replace(tzinfo=CHINA) if stamp.tzinfo is None else stamp.astimezone(CHINA)


def _download(url, request_data=None):
    data = urlencode(request_data).encode('utf-8') if request_data else None
    headers = {'User-Agent': 'Mozilla/5.0 SectorResearch/1.0'}
    if data:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    request = urllib.request.Request(url, data=data, headers=headers)
    from research_transport import fetch_bytes
    return fetch_bytes(request, timeout=8, max_bytes=4_000_000)


def membership_references(catalog):
    ids = {row['id'] for row in catalog}
    return {key: copy.deepcopy(value) for key, value in CSI_REFERENCES.items() if key in ids}


def validate_cni_identity(payload, reference):
    data = (payload.get('data') or {}) if isinstance(payload, dict) else {}
    if (not isinstance(payload, dict) or not isinstance(data, dict)
            or payload.get('code') != 200 or data.get('indexcode') != reference['code']
            or data.get('indexfullcname') != reference['title']
            or data.get('indexname') not in reference['aliases']):
        raise ValueError('国证官方指数身份与板块映射不一致')


def _xlsx_rows(content):
    """Read the publisher's simple XLSX without adding a heavyweight runtime."""
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > 100 or sum(row.file_size for row in entries) > 8_000_000:
            raise ValueError('成分工作簿展开后超过大小限制')
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(row.itertext()) for row in root.findall('x:si', ns)]
        sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        result = []
        for row in sheet.findall('x:sheetData/x:row', ns):
            cells = {}
            for cell in row.findall('x:c', ns):
                column = re.match(r'[A-Z]+', cell.get('r') or '')
                if not column:
                    continue
                value = cell.find('x:v', ns)
                if cell.get('t') == 'inlineStr':
                    inline = cell.find('x:is', ns)
                    text = ''.join(inline.itertext()) if inline is not None else ''
                elif cell.get('t') == 's' and value is not None:
                    text = strings[int(value.text)]
                else:
                    text = value.text if value is not None else ''
                cells[column.group()] = text or ''
            result.append(cells)
        return result


def _member_workbook_rows(content):
    """The current publisher download is BIFF XLS; older snapshots were XLSX."""
    if content.startswith(b'PK\x03\x04'):
        return _xlsx_rows(content)
    if content.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        import xlrd
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
        try:
            sheet = book.sheet_by_index(0)
            if sheet.nrows > 10001 or sheet.ncols > 26:
                raise ValueError('国证官方成分工作簿超过大小限制')
            rows = []
            for number in range(sheet.nrows):
                cells = {}
                for column in range(sheet.ncols):
                    cell = sheet.cell(number, column)
                    value = cell.value
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        value = xlrd.xldate_as_datetime(value, book.datemode).date().isoformat()
                    elif isinstance(value, float) and value.is_integer():
                        value = str(int(value))
                    else:
                        value = str(value)
                    # Codes can be numeric Excel cells with a six-digit display.
                    if column == 1 and cell.ctype == xlrd.XL_CELL_NUMBER and value.isdigit():
                        value = value.zfill(6)
                    cells[chr(65 + column)] = value.strip()
                rows.append(cells)
            return rows
        finally:
            book.release_resources()
    raise ValueError('国证官方成分下载未返回有效 Excel 工作簿；来源可能暂未发布该期数据')


def cni_sample_snapshot(payload, reference, as_of):
    """Use the publisher's dated first page to request its current full file."""
    data = payload.get('data') if isinstance(payload, dict) else None
    rows = data.get('rows') if isinstance(data, dict) else None
    total = payload.get('total') if isinstance(payload, dict) else None
    if (not isinstance(payload, dict) or payload.get('code') != 200
            or not isinstance(rows, list) or not rows
            or type(total) is not int or not len(rows) <= total <= 10000):
        raise ValueError('国证官方样本详情未返回可核验的完整名单数量')
    dates = set()
    today = _stamp(as_of).date()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('国证官方样本详情格式变化')
        try:
            day = datetime.strptime(row.get('dateStr', ''), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            raise ValueError('国证官方样本详情缺少有效日期') from None
        if not 0 <= (today-day).days <= 45:
            raise ValueError('国证官方样本详情日期不在研究日前45天内')
        dates.add(day.isoformat())
    if len(dates) != 1:
        raise ValueError('国证官方样本详情混有不同快照日期')
    if reference.get('requires_complete_universe') and total < reference.get('minimum_universe_size', 4000):
        raise ValueError('未取得完整全市场基池，停止微盘市值选样')
    return dates.pop(), total


def parse_cni_members(content, reference, as_of):
    rows = _member_workbook_rows(content)
    if not rows or [rows[0].get(key) for key in ('A', 'B', 'C')] != ['日期', '样本代码', '样本简称']:
        raise ValueError('国证官方成分文件表头变化')
    today = _stamp(as_of).date()
    result = {}
    for row in rows[1:]:
        try:
            day = datetime.strptime(row.get('A', ''), '%Y-%m-%d').date()
        except ValueError:
            continue
        if not 0 <= (today-day).days <= 45:
            continue
        code = row.get('B', '').strip().split('.')[0]
        # This adapter only accepts the publisher's mainland RMB common stocks.
        exchange = 'SH' if re.fullmatch(r'6\d{5}', code) else 'SZ' if re.fullmatch(r'[03]\d{5}', code) else 'BJ' if re.fullmatch(r'(?:[48]\d{5}|92\d{4})', code) else None
        if not exchange or not row.get('C'):
            continue
        ts_code = code + '.' + exchange
        if reference.get('requires_complete_universe') and ts_code in result:
            raise ValueError('全市场基池成分重复，不能建立完整市值排序')
        result[ts_code] = {'ts_code': ts_code, 'name': row['C'], 'member_date': day.isoformat(),
            'index_code': reference['code'], 'index_name': reference['title'],
            'evidence_type': 'official_index', 'source_url': CNI_BASE + 'sample-detail/download-history?indexcode=' + reference['code']}
        # The workbook's market caps belong to its membership snapshot date.
        # Retain that evidence separately; callers must never call it a live cap.
        if rows[0].get('E') == '总市值(亿元)':
            try:
                market_cap = float(row.get('E', '').replace(',', ''))
            except (ValueError, AttributeError):
                market_cap = 0
            if math.isfinite(market_cap) and market_cap > 0:
                result[ts_code]['membership_market_cap'] = market_cap * 100_000_000
                result[ts_code]['membership_market_cap_date'] = day.isoformat()
    if not result:
        raise ValueError('国证成分文件未提供研究日前45天内有效A股成员')
    if reference.get('requires_complete_universe'):
        if (len(result) != len(rows) - 1
                or len(result) < reference.get('minimum_universe_size', 4000)
                or len({row['member_date'] for row in result.values()}) != 1):
            raise ValueError('未取得同一有效日期的完整全市场基池，停止微盘市值选样')
    return list(result.values())


def _fetch_cni_members(reference, as_of):
    from research_public_data import _get, _remember
    key = 'cni_members:' + reference['code']
    cached = _get(key)
    if cached:
        today = _stamp(as_of).date()
        valid = [row for row in cached if 0 <= (today-datetime.fromisoformat(row['member_date']).date()).days <= 45]
        if reference.get('requires_complete_universe') and (
                len(valid) != len(cached)
                or len(valid) < reference.get('minimum_universe_size', 4000)
                or len({row['ts_code'] for row in valid}) != len(valid)
                or len({row['member_date'] for row in valid}) != 1):
            valid = []
        if valid:
            return valid
    identity = json.loads(_download(CNI_BASE + 'index/selectIndexByCode?codeValue=' + reference['code']).decode('utf-8'))
    validate_cni_identity(identity, reference)
    detail_url = CNI_BASE + 'sample-detail/detail?' + urlencode({
        'indexcode': reference['code'], 'dateStr': _stamp(as_of).strftime('%Y-%m'),
        'pageNum': 1, 'rows': 20, 'isFirstCall': 1})
    snapshot, total = cni_sample_snapshot(json.loads(_download(detail_url).decode('utf-8')), reference, as_of)
    download_url = CNI_BASE + 'sample-detail/download?' + urlencode({
        'indexcode': reference['code'], 'dateStr': snapshot[:7]})
    rows = parse_cni_members(_download(download_url), reference, as_of)
    if len(rows) != total or {row['member_date'] for row in rows} != {snapshot}:
        raise ValueError('国证官方工作簿与样本详情的数量或日期不一致，停止选样')
    for row in rows:
        row['source_url'] = download_url
        row['identity_url'] = CNI_BASE + 'index/selectIndexByCode?codeValue=' + reference['code']
        row['snapshot_url'] = detail_url
    _remember(key + ':last_good', rows, 45*86400)
    return _remember(key, rows, 6*3600)


def fetch_cni_members(reference, as_of):
    from research_public_data import _get, _fetched_at
    try:
        return _fetch_cni_members(reference, as_of)
    except (OSError, TimeoutError):
        key = 'cni_members:' + reference['code'] + ':last_good'
        rows = _get(key)
        today = _stamp(as_of).date()
        try:
            valid = bool(rows and all(r['index_code'] == reference['code'] and r['index_name'] == reference['title']
                and 0 <= (today - datetime.fromisoformat(r['member_date']).date()).days <= 45 for r in rows))
            if reference.get('requires_complete_universe'):
                valid = valid and len(rows) >= reference.get('minimum_universe_size', 4000) and len({r['member_date'] for r in rows}) == 1
            if valid:
                for row in rows:
                    row.update(cache_used=True, retained_fetched_at=_fetched_at(key))
                return rows
        except (ValueError, TypeError, KeyError):
            pass
        raise


def parse_business_evidence(content, evidence, reference, as_of, observed_at, max_age_seconds=6*3600):
    today, observed = _stamp(as_of), _stamp(observed_at)
    # The report timestamp marks collection start; a response can arrive seconds
    # later on the same date. The observation must never be a future-day snapshot.
    if observed.date() > today.date() or not -300 <= (today-observed).total_seconds() <= max_age_seconds:
        raise ValueError('业务证据核对时间无效')
    publication = evidence.get('published_date')
    if publication and not 0 <= (today.date()-datetime.fromisoformat(publication).date()).days <= 730:
        raise ValueError('业务证据披露日期超出可用范围')
    text = content.decode('utf-8', 'strict') if isinstance(content, bytes) else str(content)
    if evidence.get('response_kind') == 'cctc_product':
        payload = json.loads(text)
        if (not isinstance(payload, list) or len(payload) != 1 or payload[0].get('id') != 46
                or payload[0].get('name') != '多层片式陶瓷电容器'):
            raise ValueError('三环集团官网公开产品身份发生变化')
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)
    text = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>', ' ', text, flags=re.S|re.I)
    text = html.unescape(re.sub(r'<[^>]+>', ' ', text))
    text = re.sub(r'\s+', ' ', text)
    if not all(term in text for term in evidence['required']):
        raise ValueError('官方业务页面未通过公司与主题事实核对')
    return {'ts_code': evidence['ts_code'], 'name': evidence['name'],
        'member_date': observed.date().isoformat(), 'index_code': reference['code'],
        'index_name': reference['title'], 'evidence_type': 'public_business',
        'published_date': publication, 'observed_at': observed.isoformat(),
        'source_url': evidence.get('display_url') or evidence['url'], 'evidence_description': evidence['description'],
        'role': evidence.get('role') or '公开业务证据代表样本（有限样本池，非全行业龙头认证）',
        'selection_basis': '先核对官方公开业务与主题关联。' + SELECTION_METHOD + '不表示全主题市值排名或主营收入占比。'}


def fetch_business_member(evidence, reference, as_of):
    from research_public_data import _get, _remember, _fetched_at
    key = 'business_evidence:' + evidence['ts_code'] + ':' + reference['code']
    content = _get(key)
    if content is None:
        try:
            content = _download(evidence['url'], evidence.get('request_data')).decode('utf-8', 'strict')
            observed_at = now_iso()
            row = parse_business_evidence(content, evidence, reference, as_of, observed_at)
        except (OSError, TimeoutError):
            retained = _get(key + ':last_good')
            if not retained:
                raise
            row = parse_business_evidence(retained['content'], evidence, reference, as_of, retained['observed_at'], max_age_seconds=45*86400)
            row['cache_used'] = True
            return row
        _remember(key, content, 6*3600)
        _remember(key + ':last_good', {'content': content, 'observed_at': observed_at}, 45*86400)
        return row
    return parse_business_evidence(content, evidence, reference, as_of, _fetched_at(key))


def retained_business_member(evidence, reference, as_of):
    """Budget expiry cannot discard previously verified, still-dated facts."""
    from research_public_data import _get
    key = 'business_evidence:' + evidence['ts_code'] + ':' + reference['code']
    retained = _get(key + ':last_good')
    if not retained:
        return None
    try:
        row = parse_business_evidence(retained['content'], evidence, reference, as_of, retained['observed_at'], max_age_seconds=45*86400)
    except (ValueError, TypeError, KeyError):
        return None
    row['cache_used'] = True
    return row


def fetch_theme_memberships(catalog, as_of):
    """Merge memberships/references/sources into the main public-data collector.

    CSI references are returned separately by membership_references() so the
    existing CSI fetcher does not duplicate requests. This function handles CNI
    and business sources only, before quote/finance selection in the caller.
    """
    from research_public_data import _parallel, _fetched_at, _save
    ids = {row['id'] for row in catalog}
    result = {'memberships': {}, 'references': {}, 'sources': []}
    cni = {key: value for key, value in CNI_REFERENCES.items() if key in ids}
    fetched = _parallel(list(cni), lambda key: fetch_cni_members(cni[key], as_of), 18, 4, retry_key='cni_members')
    for key, (rows, error) in fetched.items():
        ref = cni[key]
        source_id = 'public:members:' + key
        rows = rows or []
        for row in rows:
            row['source_ids'] = [source_id]
        result['memberships'][key] = (rows, error)
        result['references'][key] = copy.deepcopy(ref)
        result['sources'].append({'id': source_id, 'name': '国证官方成分 · ' + ref['title'],
            'url': rows[0].get('source_url') if rows else CNI_BASE + 'sample-detail/detail?indexcode=' + ref['code'],
            'identity_url': CNI_BASE + 'index/selectIndexByCode?codeValue=' + ref['code'],
            'status': 'partial' if rows and rows[0].get('cache_used') else 'ok' if rows else 'error', 'count': len(rows),
            'as_of': max((row['member_date'] for row in rows), default=None),
            'fetched_at': rows[0].get('retained_fetched_at') or _fetched_at('cni_members:' + ref['code']) if rows else now_iso(),
            'cache_used': bool(rows and rows[0].get('cache_used')), 'error': error})
    business_sets = {**BUSINESS_EVIDENCE, **CNI_BUSINESS_FILTERS}
    business_refs = {**BUSINESS_REFERENCES, **CNI_REFERENCES}
    raw_cni = {key: {row['ts_code']: row for row in result['memberships'].get(key, ([], ''))[0]}
               for key in CNI_BUSINESS_FILTERS if key in ids}
    for key in raw_cni:
        result['memberships'][key] = ([], result['memberships'].get(key, ([], ''))[1])
    # Interleave directions; a slow early website must not starve every later
    # sector. Resolve hot cache entries before admitting any network work.
    sets = {key: rows for key, rows in business_sets.items() if key in ids}
    jobs = [(key, i) for i in range(max(map(len, sets.values()), default=0))
            for key, rows in sets.items() if i < len(rows)]
    from research_public_data import _get
    verified, pending = {}, []
    for key, i in jobs:
        evidence, ref = sets[key][i], business_refs[key]
        cache_key = 'business_evidence:' + evidence['ts_code'] + ':' + ref['code']
        if _get(cache_key) is not None:
            try:
                verified[(key, i)] = (fetch_business_member(evidence, ref, as_of), '')
                continue
            except (ValueError, TypeError, KeyError):
                pass
        pending.append((key, i))
    verified.update(_parallel(pending, lambda item: fetch_business_member(sets[item[0]][item[1]], business_refs[item[0]], as_of), 45, 12))
    errors = {}
    for (key, i), (row, error) in verified.items():
        evidence = business_sets[key][i]
        if not row and ('预算' in error or '超时' in error or 'timed out' in error):
            row = retained_business_member(evidence, business_refs[key], as_of)
        source_id = 'public:business:' + evidence['ts_code'] + ':' + key
        result['references'][key] = copy.deepcopy(business_refs[key])
        result['memberships'].setdefault(key, ([], ''))
        if row:
            row['source_ids'] = [source_id]
            if key in raw_cni:
                official = raw_cni[key].get(row['ts_code'])
                if official:
                    row.update(member_date=official['member_date'], evidence_type='official_index_business',
                        source_ids=official['source_ids'] + [source_id],
                        role='官方产业指数成分及存储业务核验样本（有限样本池，非主营龙头认证）',
                        selection_basis='先满足官方存储产业指数成员身份及公司公开存储业务两项证据。' + SELECTION_METHOD + '不以设备/晶圆代工替代存储样本。')
                    result['memberships'][key][0].append(row)
            else:
                result['memberships'][key][0].append(row)
        else:
            errors.setdefault(key, []).append(evidence['name'] + '：' + error)
        result['sources'].append({'id': source_id, 'name': evidence['title'], 'url': evidence.get('display_url') or evidence['url'],
            'status': 'partial' if row and row.get('cache_used') else 'ok' if row else 'error', 'count': 1 if row else 0,
            'as_of': evidence.get('published_date'), 'as_of_precision': 'date' if evidence.get('published_date') else 'unknown',
            'fetched_at': row.get('observed_at') if row else now_iso(), 'error': error,
            'cache_used': bool(row and row.get('cache_used')),
            'scope': evidence['description'] + ' 网页核对日期与原文发布日期分别记录；业务事实与官方成分身份分别核验。'})
    for key, messages in errors.items():
        result['memberships'][key] = (result['memberships'][key][0], '；'.join(messages))
    _save()
    return result
