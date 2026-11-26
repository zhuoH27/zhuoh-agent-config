# -*- coding: utf-8 -*-
"""PPTX 文字运行级字体设置（zhuoh-ppt-maker 生成 .pptx 时复用）。

python-pptx 的 font.name 只写入 a:latin；中文需补 a:ea、西文扩展需补 a:cs，
且三者须按 schema 顺序 latin→ea→cs 插入。行为由 tests/test_pptx_font.py 实测
覆盖（三属性写入、schema 顺序、保存重开持久）。
"""
from pptx.oxml.ns import qn


def set_run_fonts(run, zh="Microsoft YaHei", en="Times New Roman"):
    """把中英文字体写入 run 的 a:latin / a:ea / a:cs 三属性。"""
    run.font.name = en  # 写入 a:latin
    rPr = run._r.get_or_add_rPr()
    latin = rPr.find(qn("a:latin"))
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        latin.addnext(ea)  # 保持 latin→ea→cs 的 schema 顺序
    ea.set("typeface", zh)
    cs = rPr.find(qn("a:cs"))
    if cs is None:
        cs = rPr.makeelement(qn("a:cs"), {})
        ea.addnext(cs)
    cs.set("typeface", en)
