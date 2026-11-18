# -*- coding: utf-8 -*-
"""Room conflict regression: use permissioned metadata, never scrape OLX.

All data below is fictional. Structured rooms are never corrected by inference.
A contradiction blocks the import transaction rather than publishing a guess.
"""
import json
from pathlib import Path

import pytest

from scripts.market_inventory import normalise, ingest
from scripts.partner_xml import iter_partner_xml
from scripts.partner_yrl import iter_yrl
from scripts.room_claims import explicit_room_claims, has_room_conflict

PARTNER = {"allowed_source_hosts": ["agency.example.ua"]}


def row(**replace):
    base = {
        "external_id": "synthetic-1",
        "source_url": "https://agency.example.ua/offer/synthetic-1",
        "operation": "rent",
        "property_type": "apartment",
        "city": "Київ",
        "price_uah": 15000,
        "rooms": 2,
        "area_m2": 53.5,
    }
    base.update(replace)
    return base


@pytest.mark.parametrize("text,count", [
    ("Оренда 1-кімнатної квартири", 1),
    ("2-кімнатна квартира в новобудові", 2),
    ("Сдам 2-х комнатную квартиру", 2),
    ("Продажа двухкомнатной квартиры", 2),
    ("Двокімнатна квартира Київ", 2),
    ("3 кімнати", 3),
    ("4к квартира", 4),
    ("Квартира однокомнатная", 1),
])
def test_explicit_ukrainian_and_russian_labels(text,count):
    assert explicit_room_claims(text) == {count}


@pytest.mark.parametrize("text", [
    "Окрема спальня", "студія", "смарт-квартира",
    "2-х санвузлів", "2 поверх", "35 м²", "2-кімн у сусідньому будинку"[:0]
])
def test_do_not_guess_rooms_from_amenities(text):
    assert explicit_room_claims(text) == set()


def test_structured_room_count_and_source_title_must_agree():
    with pytest.raises(ValueError, match="Room count conflicts"):
        normalise(row(rooms=1,title="Двокімнатна квартира"), PARTNER)
    with pytest.raises(ValueError, match="Room count conflicts"):
        normalise(row(rooms=1,description="Оренда 2-кімнатної квартири"), PARTNER)
    with pytest.raises(ValueError, match="Room count conflicts"):
        normalise(row(rooms=2,title="2-кімн",description="1-комнатная квартира"), PARTNER)


def test_unknown_remains_unknown_even_with_one_title_claim():
    result = normalise(row(rooms=None,title="Двокімнатна"), PARTNER)
    assert result["rooms"] is None
    assert "title" not in result and "description" not in result


def test_permitted_consistent_metadata_does_not_persist_private_text():
    original = row(title="2-кімнатна квартира",description="2-х комнатная, телефон +380500000000")
    result = normalise(original,PARTNER)
    assert result["rooms"] == 2
    assert {"title","description","phone"}.isdisjoint(result)
    assert "380" not in json.dumps(result)


def test_explicit_source_text_disagreements_without_room_metadata():
    assert has_room_conflict(None,"Однокімнатна","2-кімнатна")
    assert not has_room_conflict(None,"Однокімнатна","Оренда квартири")
    assert not has_room_conflict(1,"Окрема спальня","Є бойлер")


@pytest.mark.parametrize("field,value",[
    ("title",17),("description",["2-кімн"]),
    ("title","2-кімн"+"a"*9000)
])
def test_oversized_or_invalid_transient_source_text_fails_closed(field,value):
    with pytest.raises(ValueError,match="room-claim field"):
        normalise(row(**{field:value}),PARTNER)


def test_permissioned_xml_adapter_passes_transient_title_to_gate(tmp_path):
    xml=(('<realty-feed><offer id="synthetic-1">'
           '<source_url>https://agency.example.ua/offer/synthetic-1</source_url>'
           '<operation>rent</operation><property_type>apartment</property_type>'
           '<city>Київ</city><price_uah>15000</price_uah>'
           '<rooms>1</rooms><title>Двокімнатна квартира</title>'
           '</offer></realty-feed>'))
    f=tmp_path/"feed.xml"
    f.write_text(xml,encoding="utf-8")
    parsed=list(iter_partner_xml(f))
    assert len(parsed)==1 and parsed[0]["title"]=="Двокімнатна квартира"
    with pytest.raises(ValueError,match="Room count conflicts"):
        normalise(parsed[0],PARTNER)


def test_permissioned_yrl_adapter_passes_ephemeral_description(tmp_path):
    xml=('''<realty-feed><offer internal-id="synthetic-1"><type>оренда</type>
    <property-type>житлова</property-type><category>квартира</category>
    <url>https://agency.example.ua/offer/synthetic-1</url>
    <price><value>15000</value><currency>UAH</currency><period>місяць</period></price>
    <location><country>Україна</country><locality-name>Київ</locality-name></location>
    <rooms>2</rooms><description>Однокімнатна квартира</description>
    </offer></realty-feed>''')
    p=tmp_path/"feed.xml"
    p.write_text(xml,encoding="utf-8")
    parsed=list(iter_yrl(p))
    assert len(parsed)==1 and parsed[0]["description"]=="Однокімнатна квартира"
    with pytest.raises(ValueError,match="Room count conflicts"):
        normalise(parsed[0],PARTNER)
