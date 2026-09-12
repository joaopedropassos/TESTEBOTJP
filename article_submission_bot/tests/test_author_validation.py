"""Author identity and config validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.models import AuthorConfig, AuthorEntry
from app.package_builder import load_author_config
from app.safety import SafetyError, preserve_author_order, validate_author_config
from app.settings import get_settings


def test_author_yaml_identity():
    get_settings.cache_clear()
    author = load_author_config()
    assert author.full_name == "João Pedro Pereira Passos"
    assert author.publication_name == "João Pedro Pereira Passos"
    assert str(author.corresponding_email) == "joaopedro.passos@mail.uft.edu.br"
    assert author.country == "Brasil"
    assert author.institution == ""
    assert author.orcid == ""
    corresponding = [a for a in author.authors if a.corresponding]
    assert len(corresponding) == 1
    assert corresponding[0].email == "joaopedro.passos@mail.uft.edu.br"


def test_never_invent_missing_fields():
    cfg = AuthorConfig(
        full_name="João Pedro Pereira Passos",
        publication_name="João Pedro Pereira Passos",
        corresponding_email="joaopedro.passos@mail.uft.edu.br",
        country="Brasil",
        institution="",
        orcid="",
        authors=[
            AuthorEntry(
                full_name="João Pedro Pereira Passos",
                email="joaopedro.passos@mail.uft.edu.br",
                corresponding=True,
                order=1,
                institution="",
                orcid="",
            )
        ],
    )
    gaps = validate_author_config(cfg)
    # Gaps listed, fields remain empty
    assert cfg.institution == ""
    assert cfg.orcid == ""
    assert "optional_empty:institution" in gaps
    assert "optional_empty:orcid" in gaps


def test_wrong_corresponding_email_rejected():
    cfg = AuthorConfig(
        full_name="João Pedro Pereira Passos",
        publication_name="João Pedro Pereira Passos",
        corresponding_email="jp.criatividade@gmail.com",  # Drive email — forbidden
        country="Brasil",
        authors=[
            AuthorEntry(
                full_name="João Pedro Pereira Passos",
                email="jp.criatividade@gmail.com",
                corresponding=True,
                order=1,
            )
        ],
    )
    with pytest.raises(SafetyError) as ei:
        validate_author_config(cfg)
    assert ei.value.code == "CORRESPONDING_EMAIL_MISMATCH"


def test_never_auto_reorder_authors():
    authors = [
        AuthorEntry(full_name="B", order=1, corresponding=False),
        AuthorEntry(
            full_name="João Pedro Pereira Passos",
            order=2,
            corresponding=True,
            email="joaopedro.passos@mail.uft.edu.br",
        ),
    ]
    ordered = preserve_author_order(authors)
    assert [a.full_name for a in ordered] == ["B", "João Pedro Pereira Passos"]


def test_author_yaml_file_roundtrip(tmp_path):
    src = get_settings().author_config_path
    data = yaml.safe_load(src.read_text(encoding="utf-8"))
    assert data["corresponding_email"] == "joaopedro.passos@mail.uft.edu.br"
    # Copy and reload
    dest = tmp_path / "author.yaml"
    dest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    author = load_author_config(dest)
    assert author.full_name == "João Pedro Pereira Passos"
