"""P0-05 — clés primaires composites des tables MOP.

Les tables ``mop*`` ne sont pas gérées par Django, mais leurs vraies clés
primaires sont composites. Ces tests vérifient la métadonnée Django, la
construction des lookups ORM et l'absence d'enregistrement admin (l'admin
Django 5.2–6.1 ne supporte pas les PK composites).
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib import admin
from django.core.exceptions import MultipleObjectsReturned
from django.db import connection

from results.models import (
    Mopclass,
    Mopclasscontrol,
    Mopcompetition,
    Mopcompetitor,
    Mopcontrol,
    Moporganization,
    Mopradio,
    Mopteam,
    Mopteammember,
)


MOP_MODELS = [
    (Mopcompetition, ('cid', 'id')),
    (Mopclass, ('cid', 'id')),
    (Moporganization, ('cid', 'id')),
    (Mopcompetitor, ('cid', 'id')),
    (Mopcontrol, ('cid', 'id')),
    (Mopclasscontrol, ('cid', 'id', 'leg', 'ord')),
    (Mopradio, ('cid', 'id', 'ctrl')),
    (Mopteam, ('cid', 'id')),
    (Mopteammember, ('cid', 'id', 'leg', 'ord')),
]


@pytest.mark.parametrize('model,key_fields', MOP_MODELS)
def test_composite_primary_key_fields(model, key_fields):
    assert [field.name for field in model._meta.pk.fields] == list(key_fields)
    assert model._meta.get_field('cid').primary_key is False
    assert model._meta.pk.name == 'pk'


@pytest.mark.parametrize('model,key_fields', MOP_MODELS)
def test_pk_lookup_uses_every_key_column(model, key_fields):
    values = tuple(range(1, len(key_fields) + 1))
    sql = str(model.objects.filter(pk=values).query)

    quoted_columns = [connection.ops.quote_name(field) for field in key_fields]
    assert all(column in sql for column in quoted_columns), sql
    assert all(str(value) in sql for value in values), sql


@pytest.mark.parametrize('model,key_fields', MOP_MODELS)
def test_scalar_pk_is_rejected(model, key_fields):
    """Un cid seul ne doit plus ressembler à une PK complète."""
    with pytest.raises(ValueError, match='must be a tuple or a list'):
        model.objects.filter(pk=1)


def test_same_cid_different_id_have_distinct_pk():
    first = Mopcompetitor(cid=6, id=1)
    second = Mopcompetitor(cid=6, id=2)

    assert first.pk == (6, 1)
    assert second.pk == (6, 2)
    assert first.pk != second.pk


@pytest.mark.parametrize('model,key_fields', MOP_MODELS)
def test_mop_models_are_not_registered_in_admin(model, key_fields):
    assert not admin.site.is_registered(model)


@patch('results.views.get_object_or_404', side_effect=MultipleObjectsReturned)
@patch('results.views.Mopclass')
def test_resolve_class_name_uses_first_id_when_duplicate(mock_mopclass, mock_get404):
    """Un nom de catégorie homonyme ne doit pas lever MultipleObjectsReturned."""
    from results.views import _resolve_class_id

    mock_mopclass.objects.filter.return_value.order_by.return_value.first.return_value = (
        SimpleNamespace(id=42)
    )

    assert _resolve_class_id(6, 'D21') == 42
    mock_get404.assert_called_once_with(mock_mopclass, cid=6, name='D21')
    mock_mopclass.objects.filter.assert_called_once_with(cid=6, name='D21')
    mock_mopclass.objects.filter.return_value.order_by.assert_called_once_with('id')
