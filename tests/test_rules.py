"""Offline tests for the rules engine. Run with:  python -m pytest tests  (or  python tests/test_rules.py)."""
from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acks import rules, templates  # noqa: E402
from acks.character import Character, new_character_data  # noqa: E402


def make(class_key="fighter", level=1, **attrs) -> Character:
    data = new_character_data(1, 1)
    data["class_key"] = class_key
    data["level"] = level
    for k, v in attrs.items():
        data["attributes"][k.upper()] = v
    return Character(data)


def test_attribute_mods():
    assert [rules.attr_mod(s) for s in (3, 4, 5, 6, 8, 9, 12, 13, 15, 16, 17, 18)] == \
           [-3, -2, -2, -1, -1, 0, 0, 1, 1, 2, 2, 3]


def test_fighter_attack_and_saves_match_book():
    # Attack Throws by Level: fighter 1:10, 2-3:9, 4:8, 5-6:7, 7:6, 8-9:5, 10:4, 11-12:3, 13:2, 14:1
    expected = {1: 10, 2: 9, 3: 9, 4: 8, 5: 7, 6: 7, 7: 6, 8: 5, 9: 5, 10: 4, 11: 3, 12: 3, 13: 2, 14: 1}
    for lvl, throw in expected.items():
        assert make("fighter", lvl).attack_throw() == throw, lvl
    f14 = make("fighter", 14)
    assert [f14.save_target(s) for s in rules.SAVES] == [4, 5, 6, 7, 8]
    f1 = make("fighter", 1)
    assert [f1.save_target(s) for s in rules.SAVES] == [13, 14, 15, 16, 17]


def test_other_progressions():
    assert make("thief", 13).attack_throw() == 4
    assert [make("crusader", 13).save_target(s) for s in rules.SAVES] == [7, 4, 10, 7, 9]
    assert make("mage", 13).attack_throw() == 6
    assert [make("mage", 10).save_target(s) for s in rules.SAVES] == [10, 10, 12, 8, 9]
    # priestess: mage attacks, crusader saves
    p = make("priestess", 5)
    assert p.attack_throw() == 9 and p.save_target("death") == 8
    assert [make("vaultguard", 13).save_target(s) for s in rules.SAVES] == [1, 2, 4, 4, 5]
    assert make("vaultguard", 13).attack_throw() == 2
    assert [make("ruinguard", 11).save_target(s) for s in rules.SAVES] == [4, 5, 6, 7, 8]
    assert [make("nightblade", 11).save_target(s) for s in rules.SAVES] == [7, 8, 8, 9, 9]
    assert [make("wonderworker", 10).save_target(s) for s in rules.SAVES] == [8, 8, 10, 6, 7]
    assert [make("craftpriest", 9).save_target(s) for s in rules.SAVES] == [5, 2, 9, 5, 7]
    assert [make("spellsword", 10).save_target(s) for s in rules.SAVES] == [6, 8, 9, 10, 10]


def test_damage_bonus_progression():
    assert [make("fighter", l).class_damage_bonus("melee", None) for l in (1, 2, 3, 6, 9, 12, 14)] == \
           [1, 1, 2, 3, 4, 5, 5]
    assert make("spellsword", 10).class_damage_bonus("melee", None) == 4
    assert make("paladin", 3).class_damage_bonus("missile", None) == 0
    assert make("thief", 9).class_damage_bonus("melee", None) == 0


def test_ac_with_armor_shield_dex():
    ch = make("fighter", dex=16)
    plate = ch.add_item("Plate Armor", 1, 6, "stone", "armor", "plate")
    shield = ch.add_item("Shield", 1, 1, "stone", "shield", "shield")
    ch.equip(plate["id"], "armor")
    ch.equip(shield["id"], "shield")
    assert ch.ac() == 6 + 1 + 2
    ch.data["proficiencies"].append("Fighting Style Specialization (weapon and shield)")
    assert ch.ac() == 10
    # mage gets no shield AC (no weapon & shield style) and is non-proficient in armor -> loses DEX
    m = make("mage", dex=16)
    lt = m.add_item("Leather Armor", 1, 2, "stone", "armor", "leather")
    m.equip(lt["id"], "armor")
    assert not m.armor_proficient()
    assert m.ac() == 2
    p = m.melee_profile()
    assert p.throw == rules.NONPROFICIENT_ATTACK_THROW


def test_swashbuckling_and_graceful():
    ch = make("bladedancer", 7, dex=13)
    lt = ch.add_item("Leather Armor", 1, 2, "stone", "armor", "leather")
    ch.equip(lt["id"], "armor")
    ch.data["proficiencies"].append("Swashbuckling")
    # 2 leather + 1 dex + 2 graceful (7th) + 1 swashbuckling (capped while armored)
    assert ch.ac() == 6
    ch.unequip("armor")
    assert ch.ac() == 0 + 1 + 2 + 2


def test_melee_profile_dual_and_two_handed():
    ch = make("fighter", 3, str=16)
    sword = ch.add_item("Sword", 2, Fraction(1, 6), "stone", "weapon", "sword", magic=1)
    ch.equip(sword["id"], "main")
    ch.equip(sword["id"], "off")
    p = ch.melee_profile()
    assert p.style == "dual"
    # STR +2, magic +1, dual +1, off-hand magic +1
    assert p.bonus.total == 5
    assert p.damage_die == "1d6"
    assert p.damage_bonus.total == 2 + 2 + 1  # STR, class (3rd level), magic
    ch.equip(sword["id"], "both")
    p = ch.melee_profile()
    assert p.style == "two_handed" and p.damage_die == "1d8" and p.bonus.total == 3


def test_missile_profile_ranges_and_thrown():
    ch = make("explorer", 1, dex=13, str=16)
    bow = ch.add_item("Short Bow", 1, Fraction(1, 6), "stone", "weapon", "short_bow")
    ch.equip(bow["id"], "missile")
    assert ch.missile_profile("long").bonus.total == 1 - 5
    assert ch.missile_profile().damage_bonus.total == 1  # class bonus only, no STR for bows
    jav = ch.add_item("Javelin", 3, Fraction(1, 6), "stone", "weapon", "javelin")
    ch.equip(jav["id"], "missile")
    assert ch.missile_profile().damage_bonus.total == 2 + 1  # STR for thrown + class


def test_weapon_proficiency():
    assert make("mage").weapon_proficient(rules.WEAPONS["dagger"])
    assert not make("mage").weapon_proficient(rules.WEAPONS["sword"])
    assert make("thief").weapon_proficient(rules.WEAPONS["sword"])
    assert not make("thief").weapon_proficient(rules.WEAPONS["great_axe"])
    assert not make("vaultguard").weapon_proficient(rules.WEAPONS["long_bow"])
    assert make("craftpriest").weapon_proficient(rules.WEAPONS["warhammer"])
    c = make("crusader")
    assert not c.weapon_proficient(rules.WEAPONS["sword"])
    c.data["proficiencies"].append("Martial Training (swords/daggers)")
    assert c.weapon_proficient(rules.WEAPONS["sword"])
    b = make("barbarian")
    b.options["barbarian_region"] = "jutland"
    assert b.weapon_proficient(rules.WEAPONS["two_handed_sword"])
    assert not b.weapon_proficient(rules.WEAPONS["composite_bow"])


def test_encumbrance_and_speed():
    ch = make("fighter", str=13)
    ch.add_item("Plate Armor", 1, 6, "stone", "armor", "plate")
    ch.add_item("Torches", 12, 1, "items")
    assert ch.encumbrance() == 8
    assert ch.speeds()["exploration"] == 60
    ch.data["purse"]["sp"] = 8000
    assert ch.encumbrance() == 16
    assert ch.speeds()["exploration"] == 30
    ch.add_item("Gold bars", 6, 1, "stone")
    assert ch.speeds()["band"] == "Overloaded"   # 22 > 20 + 1
    assert rules.fmt_stone(Fraction(28, 6)) == "4 4/6 st"


def test_spend_makes_change():
    ch = make("fighter")
    p = ch.data["purse"]
    p["gp"] = 3
    assert ch.spend_coins(35, "cp") == ({"gp": 1}, {})      # 1 gp -> 100 cp, 65 left
    assert (p["gp"], p["cp"]) == (2, 65)
    assert ch.spend_coins(5, "sp") == ({"gp": 1}, {})       # 1 gp -> 10 sp
    assert (p["gp"], p["sp"]) == (1, 5)
    assert ch.spend_coins(50, "cp") == ({}, {})             # enough cp: nothing broken
    p.update(pp=1, gp=0, ep=1, sp=0, cp=0)
    assert ch.spend_coins(70, "cp") == ({"pp": 1}, {})      # 1 ep can't cover 70 cp, so break the pp
    assert (p["pp"], p["ep"], p["cp"]) == (0, 1, 430)
    p.update(pp=0, gp=1, ep=1, sp=0, cp=0)
    assert ch.spend_coins(12, "sp") == ({"ep": 1, "gp": 1}, {})  # neither alone covers 12 sp: 5 + 10 sp, 3 change
    assert (p["gp"], p["ep"], p["sp"]) == (0, 0, 3)
    # paying in smaller coins when larger ones can't cover it
    p.update(pp=0, gp=0, ep=0, sp=15, cp=0)
    assert ch.spend_coins(1, "gp") == ({}, {"sp": 10})      # 1 gp paid as 10 sp
    assert (p["gp"], p["sp"]) == (0, 5)
    p.update(pp=0, gp=0, ep=1, sp=3, cp=30)
    assert ch.spend_coins(1, "gp") == ({}, {"ep": 1, "sp": 3, "cp": 20})  # largest coins first
    assert (p["ep"], p["sp"], p["cp"]) == (0, 0, 10)
    p.update(pp=1, gp=0, ep=0, sp=20, cp=0)
    assert ch.spend_coins(6, "gp") == ({"pp": 1}, {"sp": 10})  # 5 gp from the pp, 1 gp in silver
    assert (p["pp"], p["gp"], p["sp"]) == (0, 0, 10)
    p.update(pp=0, gp=1, ep=0, sp=5, cp=0)
    for args in ((2, "gp"), (151, "cp"), (5, "cp", False)):
        try:
            ch.spend_coins(*args)
            raise AssertionError(f"{args} should fail")
        except ValueError:
            pass
    assert (p["gp"], p["sp"], p["cp"]) == (1, 5, 0)        # a failed spend changes nothing


def test_animal_sheet():
    from acks.animal import Animal, new_animal_data, parse_attacks
    # Attack Throws by Level and HD (RR p. 296)
    assert [rules.monster_attack_throw(h) for h in ("1/2", "1-1", "1", "2", "3+1", "10", "20", "25")] == \
           [12, 11, 10, 9, 7, 1, -9, -9]
    p = rules.ANIMAL_PRESETS["horse_medium"]
    a = Animal(new_animal_data(1, 1, "Thunder"))
    a.data.update(speed=p.speed, normal_load=p.normal_load, max_load=p.max_load, hd="2", ac=1,
                  attacks=parse_attacks("2 hoof 1d6, bite 1d4+1"))
    assert [(x["name"], x["count"], x["damage"]) for x in a.attacks()] == [("hoof", 2, "1d6"), ("bite", 1, "1d4+1")]
    assert a.attack_throw() == 9
    assert a.speeds()["exploration"] == 180 and a.speeds()["combat"] == 60
    a.add_item("Rider and gear", 1, 25)
    assert a.speeds()["exploration"] == 180                         # 25 st <= 30 normal load
    a.add_item("Saddlebags", 1, Fraction(9, 2))
    assert a.speeds()["exploration"] == 180                         # 29.5 st: still within normal load
    it = a.add_item("Chain barding", 1, rules.barding_weight("chain", "large"), kind="barding",
                    custom={"ac": 3, "spiked": True})
    a.equip_barding(it["id"])
    assert a.ac() == 4 and a.encumbrance() == 34
    assert (a.speeds()["exploration"], a.speeds()["expedition"]) == (90, 18)   # book: 90' and 18 miles encumbered
    assert a.damage_expression(a.attacks()[0]) == "1d6+1" and a.damage_expression(a.attacks()[1]) == "1d4+2"
    a.add_item("Gold", 30000, 1, "coins")
    assert a.speeds()["exploration"] == 0                           # over the 60 st maximum load
    a.remove_item(it["id"])
    assert a.data["barding"] is None and a.ac() == 1
    # barding sizes (RR p. 141): man-sized 2/3, huge x3, gigantic x12; half-barding is half
    assert rules.barding_weight("plate", "man-sized") == 5 and rules.barding_weight("leather", "huge") == Fraction(9, 2)
    assert rules.barding_weight("scale", "gigantic") == 36 and rules.barding_weight("plate", "large", half=True) == Fraction(15, 4)
    # food and water: normal load / 10 and / 5, except the steppe horse (the table gives 2 st and 4 st)
    others = [p for p in rules.ANIMAL_PRESETS.values() if p.key != "horse_steppe"]
    assert all(p.food == Fraction(p.normal_load, 10) and p.water == Fraction(p.normal_load, 5) for p in others)
    steppe = rules.ANIMAL_PRESETS["horse_steppe"]
    assert (steppe.food, steppe.water) == (2, 4)
    # Monstrous Manual stat blocks print each animal's attack throw; the HD table must give the same value
    printed = {"camel": 9, "dog_hunting": 9, "dog_war": 8, "donkey": 9, "elephant": 2, "horse_heavy": 7,
               "horse_light": 9, "horse_medium": 8, "horse_steppe": 9, "mule": 9, "ox": 6}
    assert {k: rules.monster_attack_throw(p.hd) for k, p in rules.ANIMAL_PRESETS.items()} == printed
    elephant = parse_attacks(rules.ANIMAL_PRESETS["elephant"].attacks)
    assert [(x["name"], x["count"], x["damage"], x.get("alt", False)) for x in elephant] == \
           [("tusk", 2, "2d4", False), ("trample", 1, "4d8", True)]
    camel = parse_attacks(rules.ANIMAL_PRESETS["camel"].attacks)
    assert [(x["name"], x["damage"]) for x in camel] == [("bite", "1"), ("hoof", "1d4")]   # the bite deals 1 point


def test_animal_storage(tmp=None):
    import tempfile
    from acks.animal import Animal, new_animal_data
    from acks.storage import Storage
    with tempfile.TemporaryDirectory() as tmp:
        store = Storage(Path(tmp) / "t.db")
        ch = make("fighter")
        ch.data["name"] = "Marcus"
        store.create(ch)
        a = Animal(new_animal_data(1, 1, "Thunder"))
        a.data["owner_char"] = ch.id
        store.save_animal(a)
        assert [x.name for x in store.animals_owned_by(ch.id)] == ["Thunder"]
        assert store.animal_name_taken(1, "thunder") and not store.animal_name_taken(2, "Thunder")
        try:
            store.save_animal(Animal(new_animal_data(1, 2, "THUNDER")))
            raise AssertionError("duplicate name should fail")
        except ValueError:
            pass
        store.save_animal(Animal(new_animal_data(2, 2, "Thunder")))   # another server is fine
        orphans, _released = store.delete(ch.id)
        assert [x.name for x in orphans] == ["Thunder"] and store.get_animal(a.id).owner_char is None
        store.close()


def test_normal_men():
    # 0th level human: AC 0, attack throw 11+, saves as F0 (Fighter Saving Throws, level 0), 1/2 HD
    n = make("normal_man", 0, con=13)
    assert n.zero_level and n.attack_throw() == 11
    assert [n.save_target(s) for s in rules.SAVES] == [14, 15, 16, 17, 18]
    assert n.cls.title(0) == "Normal man" and n.xp_for_next() == 500 and n.xp_bonus_pct() == 0
    for _ in range(50):
        hp, _detail = n.roll_first_level_hp()
        assert 2 <= hp <= 5                                  # 1d4 +1 CON
    assert n.roll_first_level_hp(maximize=True)[0] == 5
    m = make("normal_man_militia", 0)
    assert m.roll_first_level_hp(maximize=True)[0] == 7   # 1d8-1
    # a commoner has no weapon proficiency: -1, so 12+, keeping his STR bonus
    club = n.add_item("Club", 1, Fraction(1, 6), "stone", "weapon", "club")
    n.equip(club["id"], "main")
    p = n.melee_profile()
    assert p.throw == 12 and p.nonproficient
    m.equip(m.add_item("Spear", 1, Fraction(1, 6), "stone", "weapon", "spear")["id"], "main")
    assert m.melee_profile().throw == 11 and not m.melee_profile().nonproficient
    # 500 XP: advance into a human class, re-roll hp with its Hit Die, keep new or old + 1
    try:
        n.level_up()
        raise AssertionError("normal men must pick a class")
    except ValueError:
        pass
    for bad in ("nightblade", "bao_warrior", "normal_man_militia"):
        try:
            make("normal_man", 0).advance_from_zero(bad)
            raise AssertionError(f"{bad} isn't a human class")
        except ValueError:
            pass
    n.data["hp"] = {"current": 3, "max": 3}
    n.data["xp"] = 500
    old, new, _detail = n.advance_from_zero("fighter")
    assert (n.cls.key, n.level, old) == ("fighter", 1, 3) and new >= 4 and "Adventuring" in n.data["proficiencies"]
    assert n.attack_throw() == 10 and n.save_target("paralysis") == 13
    weak = make("normal_man", 0, str=8)
    try:
        weak.advance_from_zero("fighter")   # key attribute STR below 9
        raise AssertionError("ineligible class")
    except ValueError:
        pass


def test_backstab():
    t = make("thief", 5, dex=16)
    dg = t.add_item("Dagger", 1, Fraction(1, 6), "stone", "weapon", "dagger")
    t.equip(dg["id"], "main")
    p = t.melee_profile(sneak=True)
    assert p.extra_dice_on_hit == 2
    assert dict(p.bonus.parts)["Backstab"] == 4
    assert p.damage_expression() == "3d4"


def test_level_up_hp():
    ch = make("fighter", con=13)
    ch.data["hp"] = {"current": 8, "max": 8}
    old, new, _ = ch.level_up()
    assert ch.level == 2 and new >= old + 1 and ch.data["hp"]["current"] == 8 + (new - old)


def test_templates_load_and_parse():
    assert len(rules.classes_by_source("Revised Rulebook")) == 21
    assert all(len(v) == 8 for v in rules.TEMPLATES.values())
    thug = templates.template_for_roll("fighter", 3)
    parsed = templates.parse_equipment(thug["equipment"])
    assert parsed.encumbrance() == Fraction(28, 6)
    kinds = {i.base for i in parsed.items if i.base}
    assert {"short_bow", "morning_star", "leather"} <= kinds
    legion = templates.template_for_roll("fighter", 11)
    parsed = templates.parse_equipment(legion["equipment"])
    assert parsed.coins == {"gp": 20}
    assert parsed.encumbrance() == 10


def test_find_weapon_aliases():
    assert rules.find_weapon("pair of scimitars").key == "short_sword"
    assert rules.find_weapon("Two-handed iron sword").key == "two_handed_sword"
    assert rules.find_weapon("long-bladed glaive").key == "polearm"
    assert rules.find_weapon("Holy symbol (hammer of Turas)") is None
    assert rules.find_weapon("2 well-balanced daggers").key == "dagger"


def test_supplement_classes_load():
    assert rules.SKIPPED_CLASSES == {}
    assert len(rules.classes_by_source("Before All Others")) == 22
    assert len(rules.classes_by_source("By This Axe")) == 10
    assert all(len(templates.templates_for(k)) == 8 for k, c in rules.CLASSES.items() if not c.zero_level)


def test_supplement_tables_match_book():
    a = make("bao_arborist", 1)   # BAO: 1-2 row is 12+ 13+ 13+ 14+ 14+, attack 10+
    assert [a.save_target(s) for s in rules.SAVES] == [12, 13, 13, 14, 14] and a.attack_throw() == 10
    assert make("bao_arborist", 13).attack_throw() == 4
    o = make("bao_oakheart", 11)  # printed 11-12 row: 4+ 6+ 7+ 8+ 8+, attack 3+
    assert [o.save_target(s) for s in rules.SAVES] == [4, 6, 7, 8, 8] and o.attack_throw() == 3
    v = make("bta_delver", 1)
    assert v.cls.max_level == 11 and v.cls.key_attributes
    assert make("bao_mountebank").cls.max_level == 12


def test_pugilist_fists_and_fury_runes():
    p = make("bta_pugilist", 5, str=13)
    prof = p.melee_profile()
    assert prof.weapon_name == "Bare fists" and prof.damage_die == "1d6"
    assert dict(p.armor_class().parts).get("Legwork") == 2
    f = make("bta_fury", 7)
    assert dict(f.armor_class().parts).get("Flesh-Runes") == 4
    chain = f.add_item("Chain Mail", 1, 4, "stone", "armor", "chain_mail")
    f.equip(chain["id"], "armor")
    assert "Flesh-Runes" not in dict(f.armor_class().parts)


def test_long_range_volleying():
    ch = make("bao_ranger", 1)
    bow = ch.add_item("Long Bow", 1, 1, "stone", "weapon", "long_bow")
    ch.equip(bow["id"], "missile")
    before = ch.missile_profile("long").bonus.total
    ch.data["proficiencies"].append("Long Range Volleying")
    assert ch.missile_profile("long").bonus.total == before + 3   # -5 becomes -2


def test_training_overrides():
    ch = make("bao_swordseer", 1)
    plate = ch.add_item("Plate", 1, 6, "stone", "armor", "plate")
    ch.equip(plate["id"], "armor")
    assert not ch.armor_proficient()
    ch.options["armor_override"] = "heavy"
    assert ch.armor_proficient()
    m = make("mage")
    assert not m.weapon_proficient(rules.WEAPONS["sword"])
    m.options["extra_weapons"] = ["sword"]
    assert m.weapon_proficient(rules.WEAPONS["sword"])
    w = make("bao_warrior")
    w.options["style_overrides"] = {"dual": False}
    assert "dual" not in w.styles() and "single" in w.styles()


def test_style_choice():
    c = make("bao_courtier")
    assert c.style_choice_pending() and {"dual", "weapon_and_shield"} <= c.styles()
    c.set_style_choice(["dual"])
    assert not c.style_choice_pending()
    assert "dual" in c.styles() and "two_handed" in c.styles() and "weapon_and_shield" not in c.styles()
    try:
        c.set_style_choice(["dual", "weapon_and_shield"])
        raise AssertionError("courtier took both styles")
    except ValueError:
        pass
    r = make("bao_ranger")
    assert len(rules.style_choices(r.cls)) == 3
    r.set_style_choice(["weapon_and_shield", "dual"])
    assert "two_handed" not in r.styles() and {"dual", "weapon_and_shield"} <= r.styles()
    assert rules.style_choices(make("fighter").cls) == []
    # templates name their starting style; the style entry isn't a real proficiency
    armiger = next(t for t in templates.templates_for("bao_courtier") if t["name"] == "Armiger")
    styles, profs = templates.template_style(armiger)
    assert styles == ["weapon_and_shield"] and "Weapon and Shield" not in profs and "Manual of Arms" in profs
    sentinel = next(t for t in templates.templates_for("bao_warrior") if t["name"].startswith("Sentinel"))
    assert templates.template_style(sentinel)[0] == ["weapon_and_shield"]
    for key in ("bao_courtier", "bao_warrior", "bao_envoy", "bao_oakheart", "bao_swordseer"):
        for t in templates.templates_for(key):
            picked = templates.template_style(t)[0]
            assert tuple(picked) in rules.style_choices(rules.CLASSES[key]), (key, t["name"])


def test_homebrew_weapons_and_armor():
    ch = make("fighter", 1, str=16)
    custom = rules.parse_custom_stats(damage="1d12", size="large", weapon_type="axes")
    axe = ch.add_item("Dragon-bone axe", 1, 1, "stone", "weapon", None, 0, "", custom)
    ch.equip(axe["id"], "main")
    p = ch.melee_profile()
    assert p.damage_die == "1d12" and p.style == "two_handed" and not p.nonproficient
    assert ch._weapon_focus(ch.item_weapon(axe)) is False
    ch.data["proficiencies"].append("Weapon Focus (axes)")
    assert ch.melee_profile().weapon_focus
    # override a book weapon: a sword that deals 1d8/1d10
    blade = ch.add_item("Heirloom blade", 1, Fraction(1, 6), "stone", "weapon", "sword", 1, "",
                        rules.parse_custom_stats(damage="1d8/1d10"))
    ch.equip(blade["id"], "main")
    p = ch.melee_profile()
    assert p.damage_die == "1d8" and p.bonus.total == 2 + 1
    ch.equip(blade["id"], "both")
    assert ch.melee_profile().damage_die == "1d10"
    # homebrew missile weapon
    sling = ch.add_item("Repeating crossbow", 1, Fraction(1, 6), "stone", "weapon", None, 0, "",
                        rules.parse_custom_stats(damage="1d4", size="missile", weapon_type="bows",
                                                 range_text="50/100/150"))
    ch.equip(sling["id"], "missile")
    mp = ch.missile_profile("medium")
    assert mp.damage_die == "1d4" and mp.weapon.ranges == (50, 100, 150)
    # homebrew armor and shield
    mail = ch.add_item("Mithral shirt", 1, 1, "stone", "armor", None, 0, "",
                       rules.parse_custom_stats(armor_ac=5, armor_type="light"))
    ch.equip(mail["id"], "armor")
    assert ch.armor_def().ac == 5 and ch.armor_category() == "light"
    tower = ch.add_item("Tower shield", 1, 2, "stone", "shield", None, 0, "",
                        rules.parse_custom_stats(armor_ac=2, armor_type="shield"))
    ch.unequip("main")
    ch.equip(tower["id"], "shield")
    assert ch.ac() == 5 + 2 + 0   # DEX 10
    # a mage can't use the homebrew axe
    m = make("mage")
    m_axe = m.add_item("Dragon-bone axe", 1, 1, "stone", "weapon", None, 0, "", custom)
    m.equip(m_axe["id"], "main")
    assert m.melee_profile().nonproficient
    for bad in ({"damage": "1d6+2"}, {"damage": "big"}, {"range_text": "30/60"}, {"range_text": "90/60/30"}):
        try:
            rules.parse_custom_stats(**bad)
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass


def test_encounter_roster():
    from acks import encounter as E
    enc = E.new_encounter(1)
    pc = make("explorer", 1, dex=16)   # +2 DEX, +1 Animal Reflexes
    pc.id = 7
    E.add_character(enc, pc)
    try:
        E.add_character(enc, pc)
        raise AssertionError("duplicate PC accepted")
    except ValueError:
        pass
    E.add_npc(enc, "Goblins", -1, 6, "enemy")
    E.add_npc(enc, "Wolf", 1, 3, "enemy", individually=True)
    E.add_npc(enc, "Hired spearmen", 0, 4, "ally")
    assert [c["name"] for c in enc["combatants"]] == [pc.name, "Goblins", "Wolf 1", "Wolf 2", "Wolf 3",
                                                     "Hired spearmen"]
    assert E.side_size(enc, "party") == 5 and E.side_size(enc, "enemy") == 9
    E.roll_round(enc, lambda cid: pc if cid == 7 else None)
    assert enc["round"] == 1
    pcs = enc["combatants"][0]
    assert pcs["modifier"] == 3 and pcs["total"] == pcs["roll"] + 3 and 1 <= pcs["roll"] <= 6
    totals = [c["total"] for c in E.order(enc)]
    assert totals == sorted(totals, reverse=True)
    # force a tie between sides: the party (5) is smaller than the enemies (9), so players choose
    enc["combatants"][0]["total"] = enc["combatants"][1]["total"] = 99
    assert any("players choose" in n for n in E.tie_notes(enc))
    E.remove(enc, enc["combatants"][1]["id"])
    assert len(enc["combatants"]) == 5
    E.roll_round(enc, lambda cid: pc if cid == 7 else None)
    assert enc["round"] == 2


def test_spell_slots():
    from acks import spells
    m = make("mage", 5)   # Revised Rulebook mage 5th: 2 / 2 / 1
    assert spells.slot_pools(m) == {"Arcane": {1: (2, 0), 2: (2, 0), 3: (1, 0)}}
    spells.cast(m, 3)
    try:
        spells.cast(m, 3)
        raise AssertionError("cast with no slot left")
    except spells.SpellError:
        pass
    spells.cast(m, 1, count=2)
    spells.refresh(m, 1)                       # one specific slot back
    assert spells.slot_pools(m)["Arcane"][1] == (2, 1)
    spells.refresh(m)                          # everything back
    assert all(used == 0 for _, used in spells.slot_pools(m)["Arcane"].values())
    m.data["level"] = 7                        # slots follow the class table as the character levels
    assert spells.slot_pools(m)["Arcane"][4] == (1, 0)
    w = make("wonderworker", 1)
    assert set(spells.slot_pools(w)) == {"Arcane", "Divine"}
    f = make("fighter")
    assert not spells.has_spells(f)
    spells.set_slots(f, 1, 2)
    assert spells.slot_pools(f) == {"Spells": {1: (2, 0)}}
    spells.set_slots(f, 1, None)
    assert not spells.has_spells(f)
    # supplement tables (Before All Others)
    assert spells.slot_pools(make("bao_wizard", 5))["Arcane"] == {1: (2, 0), 2: (2, 0), 3: (1, 0)}
    assert not spells.has_spells(make("bao_nightblade", 1)) and spells.has_spells(make("bao_nightblade", 2))
    singer = make("bao_spellsinger", 4)
    assert spells.point_pools(singer) == {"Spell points": (6, 0)}
    spells.spend_points(singer, 5)
    spells.refresh(singer)
    assert spells.point_pools(singer)["Spell points"] == (6, 0)
    singer.data["proficiencies"].append("Magical Music")    # +1 spell point per Magical Music
    assert spells.point_pools(singer)["Spell points"] == (7, 0)


def test_roll_affecting_proficiencies():
    c = make("crusader", 1, wil=13)
    assert c.save_bonus("death").total == 1
    c.data["proficiencies"].append("Divine Blessing")
    assert dict(c.save_bonus("death").parts)["Divine Blessing"] == 2
    f = make("fighter", 4)
    assert f.cleaves() == 4
    f.data["proficiencies"].append("Combat Ferocity")
    assert f.cleaves() == 5
    assert make("mage").cleaves() == 0
    r = make("explorer")
    assert r.speeds()["exploration"] == 120
    r.data["proficiencies"].append("Running")
    assert r.speeds()["exploration"] == 150 and r.speeds()["combat"] == 50
    r.add_item("Rocks", 7, 1, "stone")         # 7 st: still within Running's limit (90' + 30')
    assert r.speeds()["exploration"] == 120
    r.add_item("Rock", 1, 1, "stone")          # 8 st: Running no longer applies
    assert r.speeds()["exploration"] == 60


def test_situational_toggles():
    b = make("barbarian", 7, str=13)
    b.options["barbarian_region"] = "jutland"
    axe = b.add_item("Battle Axe", 1, Fraction(1, 6), "stone", "weapon", "battle_axe")
    b.equip(axe["id"], "main")
    base = b.melee_profile().bonus.total
    assert b.melee_profile(conditions={"berserk"}).bonus.total == base     # no Berserkergang yet
    b.data["proficiencies"] += ["Berserkergang", "Mounted Combat", "Blind Fighting", "Goblin-Slaying"]
    assert b.melee_profile(conditions={"berserk"}).bonus.total == base + 2
    assert b.melee_profile(conditions={"mounted"}).bonus.total == base + 1
    assert b.melee_profile(conditions={"blind"}).bonus.total == base - 2
    assert b.melee_profile(foe="goblinoid").bonus.total == base + 2          # +2 at 7th level
    assert make("fighter").melee_profile(conditions={"blind"}).bonus.total == -4
    p = make("paladin")
    assert dict(p.save_bonus("spells", foe="evil").parts)["Aura of Protection"] == 1
    a = make("thief", 1, dex=13)
    a.data["proficiencies"].append("Acrobatics")
    assert dict(a.save_bonus("paralysis", agility=True).parts)["Acrobatics"] == 2
    bow = a.add_item("Short Bow", 1, Fraction(1, 6), "stone", "weapon", "short_bow")
    a.equip(bow["id"], "missile")
    assert a.missile_profile("long", sneak=True).extra_dice_on_hit == 0
    a.data["proficiencies"].append("Sniping")
    assert a.missile_profile("long", sneak=True).extra_dice_on_hit == 1
    m = make("mage", 1, dex=13)
    m.data["proficiencies"] += ["Battle Magic", "Combat Reflexes"]
    assert m.initiative_bonus().total == 2 and m.initiative_bonus(casting=True).total == 2
    assert "Battle Magic" in dict(m.initiative_bonus(casting=True).parts)


def test_class_powers():
    from acks import embeds
    assert all(rules.class_powers(k) for k, c in rules.CLASSES.items() if not c.zero_level)
    have, upcoming = embeds.powers_split(make("fighter", 5))
    assert [p["name"] for p in have] == ["Manual of Arms", "Battlefield Prowess"]
    assert upcoming[0]["name"] == "Castle" and upcoming[0]["level"] == 9
    # path powers only appear once a path is chosen
    assert rules.power_paths("bao_wizard") and rules.power_paths("witch") and not rules.power_paths("fighter")
    w = make("witch", 3)
    assert not any(":" in p["name"] for p in embeds.powers_split(w)[0])
    w.options["power_path"] = "Sylvan"
    named = [p["name"] for p in embeds.powers_split(w)[0]]
    assert any(n.startswith("Sylvan:") for n in named) and not any(n.startswith("Chthonic:") for n in named)
    # optional menu powers are not owned
    assert not any(p["name"].startswith("Optional:") for p in embeds.powers_split(make("bta_sporecaster", 9))[0])
    fury = make("bta_fury", 1)
    assert dict(fury.melee_profile(conditions={"berserk"}).damage_bonus.parts)["Fighting Fury"] == 2


def test_verified_reference_data():
    from acks import embeds
    t = make("thief", 9)   # Revised Rulebook thief skills at 9th level
    line = embeds.skill_line(t)
    assert "Hiding 8+" in line and "Lockpicking 7+" in line and "Backstabbing +3d" in line
    assert "Rebuke Undead" in embeds.skill_line(make("crusader", 5))
    for key in ("crusader", "priestess", "witch", "craftpriest", "wonderworker", "bladedancer", "shaman",
                "bao_healer", "bta_earthforger", "bta_furnacewife"):
        assert any(p["name"] == "Code of Behavior" for p in rules.class_powers(key)), key
    assert "Preternatural Quickening" in dict(make("ruinguard").initiative_bonus().parts)
    # every skill table has one value per class level
    for key, tables in rules.CLASS_SKILLS.items():
        for name, vals in tables.items():
            assert len(vals) == rules.CLASSES[key].max_level, (key, name)


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failures else 0)
