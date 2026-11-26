# -*- coding: utf-8 -*-
"""zhuoh-ppt-maker 的 scripts/set_fonts.py 开发期实测。

直接加载 skill 内 scripts/set_fonts.py 的真实实现（单一事实源），验证
a:latin/a:ea/a:cs 三属性写入、schema 顺序 latin→ea→cs、保存重开后持久。
需要 python-pptx（CI 会安装，本地缺失则跳过）。
"""
import importlib.util
from pathlib import Path

import pytest

pptx = pytest.importorskip("pptx")
from pptx import Presentation  # noqa: E402
from pptx.oxml.ns import qn  # noqa: E402
from pptx.util import Inches  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skills" / "zhuoh-ppt-maker" / "scripts" / "set_fonts.py"
ZH = "Microsoft YaHei"
EN = "Times New Roman"


def _load_set_run_fonts():
    spec = importlib.util.spec_from_file_location("zhuoh_set_fonts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.set_run_fonts


def _make_run():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    p = box.text_frame.paragraphs[0]
    run = p.add_run()
    run.text = "字体测试"
    return prs, run


def test_set_run_fonts_writes_all_three():
    set_run_fonts = _load_set_run_fonts()
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
    set_run_fonts = _load_set_run_fonts()
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


def test_skill_doc_references_script():
    """SKILL.md 应引用 scripts/set_fonts.py 而非内嵌实现（防文档与测试再度漂移）。"""
    skill = (REPO / "skills" / "zhuoh-ppt-maker" / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/set_fonts.py" in skill
    assert "def set_run_fonts" not in skill, "SKILL.md 不应内嵌实现，应引用 scripts/set_fonts.py"
