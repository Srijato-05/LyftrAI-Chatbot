"""Unit tests for Settings parsing (SQLite URLs, key pool, CORS origins)."""

from pathlib import Path
from unittest.mock import patch

from app.config import Settings


def test_resolve_sqlite_path_variants(tmp_path: Path):
    s_mem1 = Settings(DATABASE_URL=":memory:")
    assert s_mem1.resolve_sqlite_path() == ":memory:"

    s_mem2 = Settings(DATABASE_URL="sqlite:///:memory:")
    assert s_mem2.resolve_sqlite_path() == ":memory:"

    # Windows drive with four slashes: sqlite:////C:/...
    win_db = (tmp_path / "sub" / "app.db").as_posix()
    s_win = Settings(DATABASE_URL=f"sqlite:////{win_db}")
    resolved_win = s_win.resolve_sqlite_path()
    assert Path(resolved_win) == Path(win_db)
    assert Path(resolved_win).parent.exists()

    # Three slashes relative/explicit path
    rel_db = (tmp_path / "rel" / "app.db").as_posix()
    s_rel = Settings(DATABASE_URL=f"sqlite:///{rel_db}")
    assert Path(s_rel.resolve_sqlite_path()) == Path(rel_db)

    # POSIX four-slash path sqlite:////data/app.db (mock mkdir to avoid touching host root)
    with patch.object(Path, "mkdir") as mock_mkdir:
        s_posix = Settings(DATABASE_URL="sqlite:////data/app.db")
        resolved_posix = Path(s_posix.resolve_sqlite_path())
        assert resolved_posix.parts[-2:] == ("data", "app.db")
        mock_mkdir.assert_called_once()


def test_parse_key_pool_whitespace_empty_and_partial_models():
    s = Settings(
        LLM_API_KEYS="  k1 , , k2 , k3 , ",
        LLM_MODEL="gemini/gemini-2.5-flash",
        LLM_MODELS="gemini/gemini-2.5-flash, gemini/gemini-2.0-flash",
    )
    pool = s.parse_key_pool()
    assert [(e.key_id, e.api_key, e.model) for e in pool] == [
        ("key_1", "k1", "gemini/gemini-2.5-flash"),
        ("key_2", "k2", "gemini/gemini-2.0-flash"),
        ("key_3", "k3", "gemini/gemini-2.5-flash"),
    ]

    s_single = Settings(LLM_API_KEYS="only-one", LLM_MODEL="gemini/gemini-2.5-flash")
    assert len(s_single.parse_key_pool()) == 1
    assert s_single.parse_key_pool()[0].key_id == "key_1"


def test_parse_allowed_origins_normalization_and_fallback():
    s = Settings(ALLOWED_ORIGINS=" https://app.vercel.app/ , http://localhost:3000/ , ")
    assert s.parse_allowed_origins() == ["https://app.vercel.app", "http://localhost:3000"]

    s_empty = Settings(ALLOWED_ORIGINS="   ")
    assert s_empty.parse_allowed_origins() == ["http://localhost:3000"]

