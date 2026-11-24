# -*- coding: utf-8 -*-
"""zhuoh-ppt-maker SKILL 中 set_run_fonts 片段的开发期实测。

片段与 skills/zhuoh-ppt-maker/SKILL.md 保持一致；需要 python-pptx（CI 会安装，
本地缺失则跳过）。验证目标：a:latin/a:ea/a:cs 三属性写入、schema 顺序
latin→ea→cs、保存重开后持久。
"""
import pytest

pptx = pytest.importorskip("pptx")
from pptx import Presentation  # noqa: E402
from pptx.oxml.ns import qn  # noqa: E402
from pptx.util import Inches  # noqa: E402

ZH = "Microsoft YaHei"
EN = "Times New Roman"


def set_run_fonts(run, zh="Microsoft YaHei", en="Times New Roman"):
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


def _make_run():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    p = box.text_frame.paragraphs[0]
    run = p.add_run()
    run.text = "字体测试"
    return prs, run


def test_set_run_fonts_writes_all_three():
    prs, run = _make_run()
    set_run_fonts(run)
    rPr = run._r.get_or_add_rPr()
    latin = rPr.find(qn("a:latin"))
    ea = rPr.find(qn("a:ea"))
    cs = rPr.find(qn("a:cs"))
    assert latin is not None and latin.get("typeface") == EN
    assert ea is not None and ea.get("typeface") == ZH
    assert cs is not None and cs.get("typeface") == EN
    order = [list(rPr).index(el) for el in (latin, ea, cs)]
    assert order == sorted(order), "schema 顺序应为 latin→ea→cs"


def test_set_run_fonts_survives_save_reload(tmp_path):
    prs, run = _make_run()
    set_run_fonts(run)
    out = tmp_path / "font_test.pptx"
    prs.save(str(out))
    prs2 = Presentation(str(out))
    run2 = prs2.slides[0].shapes[0].text_frame.paragraphs[0].runs[0]
    rPr2 = run2._r.get_or_add_rPr()
    assert rPr2.find(qn("a:latin")).get("typeface") == EN
    assert rPr2.find(qn("a:ea")).get("typeface") == ZH
    assert rPr2.find(qn("a:cs")).get("typeface") == EN


def test_snippet_matches_skill_doc():
    """片段应与 SKILL.md 中的参考片段一致（防止文档与测试漂移）。"""
    from pathlib import Path

    skill = (Path(__file__).resolve().parent.parent / "skills" / "zhuoh-ppt-maker" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    start = skill.index("from pptx.oxml.ns import qn")
    end = skill.index("```", start)
    doc_snippet = skill[start:end].strip()
    test_snippet = _snippet_source()
    assert doc_snippet == test_snippet, "tests 与 SKILL.md 的片段已不一致，请同步更新"


def _snippet_source():
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(set_run_fonts))
    lines = [l.rstrip() for l in src.strip().splitlines()]
    header = ["from pptx.oxml.ns import qn"]
    return "\n".join(header + lines)
