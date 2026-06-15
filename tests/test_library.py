"""Tests for the media store + match registration (library.py)."""

import io
import os
import sys
import zipfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_slugify_strips_leading_date():
    import library
    assert library.slugify("2026-06-10 Hub City vs FC Fred", date(2026, 6, 10)) \
        == "2026-06-10-hub-city-vs-fc-fred"
    assert library.slugify("Hub City vs FC Fred", date(2026, 6, 10)) \
        == "2026-06-10-hub-city-vs-fc-fred"
    assert library.slugify("", date(2026, 6, 10)) == "2026-06-10-match"


def test_create_match_unique_slug(lib_env):
    db, library = lib_env
    with db.session() as s:
        m1 = library.create_match(s, "Match A", date(2026, 6, 10))
        m2 = library.create_match(s, "Match A", date(2026, 6, 10))
    assert m1.slug != m2.slug
    assert m2.slug.endswith("-2")


def test_register_file_subfolders(lib_env, tmp_path):
    db, library = lib_env
    src = tmp_path / "report.pdf"
    src.write_text("pdf")
    with db.session() as s:
        m = library.create_match(s, "Reg Test", date(2026, 6, 10))
        media = library.register_file(s, m, "report_pdf", str(src), "Report")
        assert media is not None
        assert "/reports/" in media.path
        assert os.path.exists(library.abs_path(media))


def test_register_file_missing_source(lib_env):
    db, library = lib_env
    with db.session() as s:
        m = library.create_match(s, "Missing", date(2026, 6, 10))
        assert library.register_file(s, m, "report_pdf", "/nope.pdf") is None


def test_export_zip_contains_files_and_manifest(lib_env, tmp_path):
    db, library = lib_env
    src = tmp_path / "events.csv"
    src.write_text("a,b\n1,2\n")
    with db.session() as s:
        m = library.create_match(s, "Zip Test", date(2026, 6, 10))
        library.register_file(s, m, "events_csv", str(src), "Events")
        slug = m.slug
    data = library.export_zip(slug, {"slug": slug, "name": "Zip Test"})
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert any(n.endswith("match.json") for n in names)
    assert any(n.endswith("events.csv") for n in names)


def test_delete_match_removes_rows_and_folder(lib_env, tmp_path):
    db, library = lib_env
    src = tmp_path / "r.pdf"
    src.write_text("x")
    with db.session() as s:
        m = library.create_match(s, "Del Test", date(2026, 6, 10))
        library.register_file(s, m, "report_pdf", str(src))
        slug = m.slug
    assert library.delete_match(slug) is True
    assert not os.path.exists(library.match_dir(slug))
    with db.session() as s:
        assert s.query(db.Match).count() == 0
        assert s.query(db.MediaFile).count() == 0
