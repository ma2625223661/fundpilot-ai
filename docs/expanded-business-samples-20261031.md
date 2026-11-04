# 2026-10-31 扩大公司业务样本核验记录

本轮不调用付费 AI、不改密钥、不重启服务。仅扩展官方成分来源及有明确公开业务证据的公司样本。

## 结果

- AI应用：增加国证 980112 官方身份及成分采集映射；2026-09-30 名单实取 50 家。
- 微盘：增加国证A股指数 399317 完整基池，2026-09-30 名单实取 5,262 家。它是独立市值筛选的基池，不是官方微盘指数。
- 官方名单原始文件的市值仅 4,990 家有有效正值，272 家为空；字段 membership_market_cap/date 保留名单日期，不能称为实时市值。
- 微盘基池解析拒绝重复、丢弃无效行、混日期、过期或不足规模的名单；残缺缓存重新获取。当前价格、财务、样本排序由主采集器单独核验。
- 新增及复用归属证据共 28 项，实际官网 HTML 经生产 parse_business_evidence 全部通过；详见 work/expanded-business-production-parser.json。
- 本轮主题回归共 25 项通过：test_expanded_business_pools、test_new_direction_business_pools、test_research_theme_memberships。

## 业务池规模

| 方向 | 样本数 | 公司代码 |
|---|---:|---|
| 汽车整车 · 公开整车制造业务核验样本池 | 3 | 600104.SH 上汽集团、601238.SH 广汽集团、601633.SH 长城汽车 |
| 多元金融 · 金融控股及租赁有限样本池 | 3 | 000987.SZ 越秀资本、600390.SH 五矿资本、000415.SZ 渤海租赁 |
| 国产算力 · 公开业务核验样本池 | 3 | 688256.SH 寒武纪、688047.SH 龙芯中科、603019.SH 中科曙光 |
| 可控核聚变 · 公开业务核验样本池 | 3 | 600875.SH 东方电气、601727.SH 上海电气、000969.SZ 安泰科技 |
| CPO · 公开业务核验样本池 | 4 | 300394.SZ 天孚通信、002281.SZ 光迅科技、688313.SH 仕佳光子、000988.SZ 华工科技 |
| PCB · 公开业务核验样本池 | 6 | 002916.SZ 深南电路、300476.SZ 胜宏科技、002463.SZ 沪电股份、603228.SH 景旺电子、688183.SH 生益电子、002436.SZ 兴森科技 |
| MLCC · 公开业务核验样本池 | 3 | 000636.SZ 风华高科、300408.SZ 三环集团、603678.SH 火炬电子 |
| 算力租赁 · 公开业务核验样本池 | 3 | 688158.SH 优刻得、688316.SH 青云科技、920493.BJ 并行科技 |
| 稀土永磁 · 公开业务核验样本池 | 3 | 300748.SZ 金力永磁、600366.SH 宁波韵升、000970.SZ 中科三环 |
| 机械与高端制造 · 工程机械及液压有限样本池 | 4 | 600031.SH 三一重工、601100.SH 恒立液压、000425.SZ 徐工机械、000157.SZ 中联重科 |
| 锂矿 · 公开资源业务核验样本池 | 3 | 002460.SZ 赣锋锂业、002466.SZ 天齐锂业、002738.SZ 中矿资源 |
| 农林牧渔 · 种业饲料及养殖有限样本池 | 3 | 300498.SZ 温氏股份、000876.SZ 新希望、000998.SZ 隆平高科 |
| 油气资源 · 公开勘探开发业务核验样本池 | 2 | 600938.SH 中国海油、603619.SH 中曼石油 |
| 黄金矿业股票 · 公开采矿业务核验样本池 | 3 | 601899.SH 紫金矿业、600547.SH 山东黄金、600988.SH 赤峰黄金 |
| 大宗商品·资源企业股票 · 金属采矿及油气有限样本池 | 8 | 601899.SH 紫金矿业、600938.SH 中国海油、600547.SH 山东黄金、600988.SH 赤峰黄金、603619.SH 中曼石油、002460.SZ 赣锋锂业、002466.SZ 天齐锂业、002738.SZ 中矿资源 |
| 脑机接口 · 设备及临床研究关联有限样本池 | 3 | 688626.SH 翔宇医疗、301293.SZ 三博脑科、002925.SZ 盈趣科技 |
| 保险 · 公开保险业务核验样本池 | 4 | 601601.SH 中国太保、601319.SH 中国人保、601628.SH 中国人寿、601336.SH 新华保险 |

## 本轮新增证据来源

原文发布日期未知时仍为 unknown，不以采集时间替代。以下网页均实际取得可见正文，不接受只有导航、JS、注释或无法访问的页面作为新增业务证据。

| 方向 | 主体 | 原文日期 | 可见正文核验事实 | 来源 |
|---|---|---|---|---|
| sector_auto_vehicle | 600104.SH 上汽集团 | unknown | 上市公司官网披露整车业务及整车制造基地；不以单纯零部件、经销商代替整车制造样本。 | https://www.saicmotor.com/m/gsgk/gsjs/index.shtml |
| sector_auto_vehicle | 601238.SH 广汽集团 | unknown | 上市公司官网披露整车研发与制造业务，兼营零部件和服务；不推定整车业务收入占比。 | https://www.gacgroup.com/cn/about |
| sector_auto_vehicle | 601633.SH 长城汽车 | unknown | 上市公司官网披露整车设计、研发、生产及销售业务与旗下汽车品牌；不以整车零部件供应商替代整车厂。 | https://www.gwm.com.cn/aboutUs.html |
| sector_diversified_finance | 000987.SZ 越秀资本 | unknown | 上市公司官网披露融资租赁、不良资产管理及投资管理等多元金融业务；区别于银行或纯证券经纪样本。 | https://www.yuexiu-finance.com/capital/gongsijianjie.html |
| sector_diversified_finance | 600390.SH 五矿资本 | unknown | 上市公司官网披露信托、金融租赁等金融控股业务；以金融集团合并财务分析，不推定各牌照收入占比。 | https://www.minmetals-finance.com/introduction.html |
| sector_diversified_finance | 000415.SZ 渤海租赁 | unknown | 上市公司官网披露租赁集团身份及飞机租赁、租赁资产管理业务；与金控形成有限多元金融池，非全行业覆盖。 | http://www.bohaileasing.com/ |
| sector_domestic_computing | 603019.SH 中科曙光 | unknown | 上市公司官网披露高端计算、智能计算及服务器产品；不据此将全部产品认定为自主芯片。 | https://www.sugon.com/about/index |
| sector_nuclear_fusion | 000969.SZ 安泰科技 | 2026-03-27 | 上市公司官网披露已研制的核聚变包层零件、第一壁及模块；联合实验室和装备业务不等同核聚变收入占比。 | http://www.atmcn.com/mtzx/gsxw/2026/0327/5020.html |
| sector_cpo | 688313.SH 仕佳光子 | unknown | 公司官网披露展出的硅光CPO用高功率CW激光器芯片；产品展示不等同CPO规模收入。 | https://www.sjphotons.com.cn/about/exhibitiondetail/23 |
| sector_cpo | 000988.SZ 华工科技 | 2025-09-12 | 公司官网披露子公司华工正源的CPO光引擎研发与实时展示；不推定上市公司CPO收入占比。 | https://www.hgtech.com.cn/gsxw/4269.jhtml |
| sector_pcb | 002463.SZ 沪电股份 | unknown | 上市公司官网披露印制电路板研发设计和生产制造及封装载板业务；不推定主营市占率。 | https://www.wustec.com/about.php |
| sector_pcb | 603228.SH 景旺电子 | unknown | 上市公司官网披露PCB制造、柔性电路板、高密度互连板及高多层电路板产品。 | https://www.kinwong.com/ |
| sector_pcb | 688183.SH 生益电子 | unknown | 上市公司官网披露印制电路板制造业务；主体为生益电子，区别于覆铜板企业生益科技。 | https://www.sye.com.cn/gywm/index.aspx |
| sector_pcb | 002436.SZ 兴森科技 | unknown | 上市公司官网披露PCB设计、制造、贴装与样板数字化工厂；不以覆铜板材料业务替代PCB制造。 | https://www.chinafastprint.com/about |
| sector_mlcc | 603678.SH 火炬电子 | unknown | 公司官网披露火炬牌多层陶瓷固定电容器产品和MLCC研发；不将单层电容或上游粉体材料替代MLCC。 | http://www.torch.cn/research.php |
| sector_compute_leasing | 920493.BJ 并行科技 | unknown | 上市公司官网披露GPU及超算云资源按需付费服务；使用现行北交所代码920493，非原代码839493。 | https://www.paratera.com/ |
| sector_rare_earth_magnet | 000970.SZ 中科三环 | unknown | 上市公司官网披露旗下烧结及粘结钕铁硼永磁体制造企业；不以单纯稀土开采替代永磁业务。 | https://www.san-huan.com.cn/About/Company |
| sector_manufacturing | 000425.SZ 徐工机械 | unknown | 上市公司官网披露起重、挖掘等工程机械产品；仅代表工程机械制造子领域。 | https://www.xcmg.com/ |
| sector_manufacturing | 000157.SZ 中联重科 | unknown | 上市公司官网披露混凝土机械、工程起重机械等产品；仅代表工程机械制造子领域。 | https://www.zoomlion.com/ |
| sector_lithium_mining | 002738.SZ 中矿资源 | unknown | 上市公司官网披露锂矿开采及锂盐研发生产销售；采矿与加工业务并存，不推定锂矿收入占比。 | https://www.sinomine.cn/ |
| gold | 600988.SH 赤峰黄金 | unknown | 上市公司官网披露黄金采选及销售业务；采用矿业公司股价及财务，不等同黄金现货价格。 | https://www.cfgold.com/ |
| commodities | 600988.SH 赤峰黄金 | unknown | 上市公司官网披露黄金采选及销售业务；采用矿业公司股价及财务，不等同黄金现货价格。 | https://www.cfgold.com/ |
| commodities | 002738.SZ 中矿资源 | unknown | 上市公司官网披露锂矿开采及锂盐研发生产销售；采矿与加工业务并存，不推定锂矿收入占比。 | https://www.sinomine.cn/ |
| sector_brain_computer | 002925.SZ 盈趣科技 | 2025-06-12 | 上市公司官网披露脑机接口课程合作及便携式脑电设备；教学与研究关联不证明规模收入或成熟医疗产品。 | https://www.intretech.com.cn/Ne_d_gci_19_id_239.html |
| sector_insurance | 601628.SH 中国人寿 | 2026-09-22 | 上市公司官网披露寿险保险主体及业务；有限保险公司样本，不据此认定全行业龙头排名。 | https://www.e-chinalife.com/xxpl/gywm/gsjs/ |
| sector_insurance | 601336.SH 新华保险 | unknown | 上市公司官网披露A股身份及全面寿险产品与服务；不以参股保险的公司替代保险主体。 | https://www.newchinalife.com/spage/cn/companyProfileAboutXH/index.html |
| sector_memory_chip | 688123.SH 聚辰股份 | unknown | 公司官网披露EEPROM及NOR Flash芯片产品；同时核对国证存储芯片产业当前成员。 | https://www.giantec-semi.com/ |
| sector_memory_chip | 688525.SH 佰维存储 | unknown | 公司官网披露半导体存储器及嵌入式存储、内存产品；同时核对国证存储芯片产业当前成员。 | https://www.biwin.com.cn/ |

## 语义边界及未强行补入项

- 资源企业股票共 8 家，涵盖金属矿业、锂资源及油气。不是商品现货或期货价格指标。复用证据时使用深拷贝，避免跨方向污染。
- 脑机接口仍为设备、教学及临床研究关联；不依据课程、实验室、未来项目认定规模收入或主营龙头。
- CPO以明确CPO器件、光源、光引擎及方案事实入池，普通800G光模块业务本身不够。
- PCB新生益电子688183是电路板制造主体，未将生益科技600183覆铜板材料业务替代PCB制造。
- 并行科技官网现行证券代码为920493，采用920493.BJ；未沿用旧839493。
- 存储芯片核验池扩至5：兆易创新、澜起科技、江波龙、聚辰、佰维，均要求官方980138当前成员+各自存储产品事实。普冉官网业务虽明确，但不在此次980138成分，不据此强加。
- 农业当前3家，油气当前2家。海大521、牧原/大北农仅JS壳、广汇HTTPS证书错误，尚未以合格正文补满；网络失败不等同公司业务不符。
- 火炬电子、安泰科技、渤海租赁采用实际可用的官方HTTP公开页面，没有绕过TLS校验或把HTTPS证书失败当成功。
- 各池仍是有限公开业务样本；原生指数身份、所属业务、当前报价、披露日财务和近期历史分别验证，不能用业务页面替代行情或财务数据。

## 可重复检查

```powershell
E:\python\python.exe work/validate_expanded_business.py
E:\python\python.exe -m unittest test_expanded_business_pools test_new_direction_business_pools test_research_theme_memberships -q
```
