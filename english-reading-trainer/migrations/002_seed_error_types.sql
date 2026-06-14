-- Migration 002: seed closed error-type enumeration
-- Matches §2 of docs/design.md exactly.
-- Uses INSERT OR IGNORE — safe to re-run.

INSERT OR IGNORE INTO error_types (code, name, layer) VALUES
    -- Grammar layer
    ('G01', '长主语识别失败',                                    'grammar'),
    ('G02', '后置定语修饰对象判断错',                             'grammar'),
    ('G03', '嵌套从句边界混乱',                                   'grammar'),
    ('G04', '倒装 / 强调结构',                                    'grammar'),
    ('G05', '非谓语动词（分词 / 不定式）作用判断错',               'grammar'),
    ('G06', '省略 / 替代识别失败',                                'grammar'),
    ('G07', '平行结构对应失败',                                   'grammar'),
    -- Lexical layer
    ('L01', '多义词在当前语境的义项判断错',                        'lexical'),
    ('L02', '假朋友 / 形近词混淆',                                'lexical'),
    ('L03', '搭配（动名 / 形名 / 介词）不熟',                     'lexical'),
    ('L04', '词根 / 词族联想不足',                                'lexical'),
    ('L05', '习语 / 固定短语未识别',                              'lexical'),
    ('L06', '学术词汇陌生',                                      'lexical'),
    -- Discourse layer
    ('D01', '代词指代对象判断错（it / they / which / that）',     'discourse'),
    ('D02', '让步 / 对比逻辑（while / although / however）误读', 'discourse'),
    ('D03', '因果 / 推论连词误读',                               'discourse'),
    ('D04', '信息焦点（主述位）判断错',                           'discourse'),
    ('D05', '篇章衔接（this / these / such）回指失败',            'discourse');
