import pytest
from pydantic import ValidationError
from app.modules.projects.schemas import ProjectCreate


def test_project_key_is_normalized():
    project = ProjectCreate(key="evi1", name="Evidence")
    assert project.key == "EVI1"


def test_project_key_rejects_symbols():
    with pytest.raises(ValidationError):
        ProjectCreate(key="EV-I", name="Evidence")
