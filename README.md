# ACKS II Character Sheet Bot

A Discord bot that keeps **Adventurer Conqueror King System II** character sheets for your players and rolls
attacks and saves straight from them.

> **You need the books.** This bot is a play aid, not a replacement for the rules. Do not use it unless you
> have purchased the ACKS II source books it draws on (the **Revised Rulebook**, **Before All Others**, and
> **By This Axe**) from [Autarch LLC](https://autarch.co). All ACKS II game content in this repository is the
> property of Autarch LLC and is **not** licensed; see [Licence](#licence).

**Classes:** 53 classes in all: the 21 from the **Revised Rulebook**, 22 elven and gnomish classes from
**Before All Others** (v37), and 10 dwarven classes from **By This Axe**. Each has its own XP, titles,
attack-throw and saving-throw tables, combat proficiencies, and 8 templates.

- **Creation wizard** (`/create`): roll attributes the ACKS II way (5d6 drop 2 / 4d6 drop 1 / 3d6), pick from
  the classes you qualify for, roll hit points, roll 3d6 for a **class template** (all 168 templates from the
  Revised Rulebook, with gear, proficiencies, and coins filled in and auto-equipped), then name the character.
- **Sheets** (`/sheet`): attributes, HP bar, AC with its breakdown, attack throw, saving throws, melee and
  missile attack lines, encumbrance and speeds, purse, proficiencies, with buttons for the Inventory and Notes pages.
- **Attacks** (`/mattack`, `/rattack`): give the target's AC; the bot applies every bonus and penalty on the
  sheet and reports the roll, the modifiers, the number needed, **HIT** or **MISS**, and damage on a hit.
- **Saves** (`/save_paralysis`, `/save_death`, `/save_blast`, `/save_implements`, `/save_spells`).
- **Inventory** in **stone**, **items** (6 = 1 stone), or **coins** (1,000 = 1 stone); a coin purse; equip and
  unequip weapons, armor, and shields, with AC and to-hit updated to match.
- **HP**, **XP**, **level-ups** (HP rerolled per the rules), **modifiers** for magic items and spells, **proficiencies**.

## Setup

Each group runs its own copy of the bot, with its own Discord bot account and token.

1. **Get the files**
   - **Easiest:** on this page, click the green **Code** button → **Download ZIP**, then extract the ZIP
     somewhere permanent (e.g. `Documents\acks_discord_bot`). Run the commands below from inside that folder.
   - **With git:** `git clone https://github.com/JBurrwalky/acks-discord-bot.git`. Run `git pull` later to get updates.
   - You also need **Python 3.10 or newer** from <https://www.python.org/downloads/>. On Windows, tick
     **Add python.exe to PATH** in the installer.
2. **Create the bot in Discord**
   1. Open <https://discord.com/developers/applications> → **New Application**.
   2. **Bot** tab → **Reset Token** → copy the token.
   3. **OAuth2 → URL Generator**: tick the scopes `bot` and `applications.commands`, and the bot permissions
      **Send Messages**, **Embed Links**, and **Use External Emojis**. Open the generated URL and add the bot to your server.
3. **Configure**: copy `.env.example` to `.env` and paste the token after `DISCORD_TOKEN=`.
   Also set `GUILD_ID` to your server's ID (right-click the server → *Copy Server ID*, with Developer Mode on)
   so commands appear instantly instead of after up to an hour.
4. **Install and run** (Python 3.10+):

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python bot.py
   ```

   On macOS or Linux, activate with `source .venv/bin/activate` instead. The bot runs while that window is open.

Keep your `.env` file private: the token in it lets anyone run your bot. If it leaks, reset it on the
Discord **Bot** tab.

Characters are saved in `data/acks.db` (SQLite). Back that file up to keep your campaign safe.

**Judges**: anyone with *Manage Server* permission, or a role named `Judge` (change it with `JUDGE_ROLE` in
`.env`), can view and edit every character. Every command that takes a `character` option shows a Judge all
characters in the server. Everyone else can only change their own characters, but can view anyone's sheet.

## Commands

Most commands take an optional `character`. If you leave it out, the command uses your **active** character,
which you set with `/character select`.

| Command | What it does |
|---|---|
| `/create` | Start the character creation wizard (private to you). It can also make 0th-level normal men and henchmen |
| `/sheet [character] [page] [private]` | Show a sheet: `sheet`, `inventory`, or `notes` page |
| `/character list` · `select` · `delete` | Manage your characters |
| `/character edit` · `notes` | Name, alignment, homeland, description; free-form notes (spells, languages...) |
| `/character attributes str:… dex:…` | Change attribute scores |
| `/character powers [all_levels]` | Class powers the character has at their level (and what's coming) |
| `/character path` | Choose a tradition, sect, dark path, or sigil, so only that path's powers show |
| `/character training` | Extra armor, weapons, or fighting styles from class choices or powers (e.g. `style_choice` for a courtier's dual weapons, an earthforger's sigil allowing heavier armor) |
| `/character set_level` · `barbarian` · `give` | Fix a level; set a barbarian's region and damage type; reassign a character (Judge) |
| `/xp amount` | Award XP. Applies the key-attribute bonus unless `apply_bonus:False` |
| `/levelup [into]` | Gain a level when you have the XP; rerolls HP per the rules. Normal men pick the human class they become with `into` |
| `/character promote character` | Make a henchman a full party member (their player, their employer's player, or a Judge) |
| `/mattack target_ac [situational] [backstab] [raging] [mounted] [blind] [foe]` | Melee attack with equipped weapon(s) |
| `/rattack target_ac [range] [situational] [backstab] [raging] [mounted] [blind] [foe]` | Missile attack; `range` short / medium (−2) / long (−5) |
| `/save_paralysis` `/save_death` `/save_blast` `/save_implements` `/save_spells` `[source] [agility]` | Saving throws (WIL, Divine Blessing, and modifiers applied) |
| `/initiative [casting]` | 1d6 + DEX and other initiative bonuses |
| `/spell slots` | Show remaining spell slots (also on the sheet) |
| `/spell cast level [pool] [count] [spell]` · `cast points` | Spend slots of a spell level (or spell points for spellsingers) |
| `/spell refresh [level] [count] [pool]` | With `level`: restore one slot (or `count`) of that level. Without: restore all slots |
| `/spell set_slots level slots [pool]` · `set_points` | Set slots per day by hand (homebrew, bonuses, or classes the bot has no table for); `reset:True` goes back to the class table |
| `/encounter start` | Initiative wizard: tick the party (pre-filled with everyone's active character), add monsters/NPCs/groups, then roll |
| `/encounter next_round` · `add` · `add_character` · `remove` · `show` · `end` | Run the fight: reroll for a new round, add or remove combatants (newcomers roll right away), repost the roster, or end and delete it |
| `/roll dice` · `/throw target modifier` | Any dice (`2d6+1`, `4d6kh3`); a generic d20 throw vs. a target |
| `/help [public]` | List every command (only you see it unless `public:True`) |
| `/item add name [quantity] [weight] [unit] [base] [magic] [notes]` | Add any item, from the books or not. `unit` = stone, items, or coins. Leave out `weight` and common gear gets its usual weight, counted as the templates do (*Quiver with 20 arrows* or *20 arrows* = 1 item, 6 torches = 1 stone, rope = 1 stone); anything unrecognised counts as 1 item. Set `base` (e.g. *Sword*, *Chain Mail Armor*) to make it a book weapon or armor that can be equipped |
| `/item add … damage size weapon_type range thrown` · `armor_ac armor_type` | Homebrew weapon or armor stats (see below) |
| `/item remove` · `list` · `edit` | Remove, list, or edit items (`edit` can also change or clear homebrew stats) |
| `/purse add` · `spend` · `set` | Coins (pp, gp, ep, sp, cp). `spend` makes change: short of the coin you spend, it breaks the fewest larger coins (smallest first) and keeps the change, e.g. 35 cp from gold breaks 1 gp and leaves 65 cp. If the larger coins can't cover it, the rest is paid in smaller coins (largest first), e.g. 1 gp as 10 sp. `make_change:False` turns this off |
| `/equip item [slot]` · `/unequip slot` | Slots: main hand, off hand, both hands, missile, armor, shield |
| `/hp damage` · `heal` · `set` · `show` | Hit points |
| `/modifier add name target value` · `remove` · `list` | Ring of protection, *bless*, blindness... Targets: attacks, damage, AC, saves, initiative |
| `/proficiency add` · `remove` | Proficiencies (autocompletes from your class list and the general list) |
| `/animal create name [preset] [war_trained] [owner] ...` | Make an animal sheet. `preset` fills in the book's stats |
| `/animal sheet` · `list` · `edit` · `delete` | Show, list (all, or one character's), change, or delete animals |
| `/animal attack animal target_ac [attack]` · `hp` | Roll its attack routine (or one attack); damage, heal, or set HP |
| `/animal barding` · `equip` · `unequip` | Add book barding weighed for its size and put it on; swap barding |
| `/animal item add` · `remove` · `ability add` · `remove` · `routine add` · `remove` | Its gear, special abilities, and attacks |

## Spell slots

The bot tracks spell slots only, not spell rules. Each caster's slots per day come from their class table at
their current level: the Revised Rulebook casters and 14 Before All Others classes, with separate **Arcane** and
**Divine** pools for the Nobiran wonderworker and elven druid, and spell points for the spellsinger. By This
Axe classes use invocations, rhetoric, or brewing rather than daily castings, so they have no slots.

- `/spell cast level:2` spends a 2nd-level slot; add `pool:Divine` when a class has two pools, `count:2` for
  several, and `spell:` to name it for the table. Spellsingers use `/spell cast points:3`.
- `/spell refresh level:2` restores one 2nd-level slot; `/spell refresh` restores everything (after rest).
- `/spell set_slots` overrides a level's slots (or gives slots to any class), and slots grow automatically
  when the character levels up.
- The sheet shows ◆ available and ◇ spent slots.

## Henchmen and normal men

**Henchmen.** On the wizard's last step, turn on **Henchman** and pick the character who employs them (one of
yours; a Judge can pick anyone's). Any class can be a henchman. For one above 1st level, create them and then
use `/character set_level`. A henchman's sheet says whom they serve, and the employer's sheet lists their
henchmen. Making a henchman doesn't change your active character. `/character promote` makes a henchman a full
party member, and deleting an employer leaves their henchmen unemployed.

**0th-level normal men** are the wizard's **0th Level** book (Judges Journal, *0th Level NPC Hit Dice*):

| | Commoner | Militia/mercenary |
|---|---|---|
| Hit Dice | 1/2 HD (1d4 hp + CON) | 1-1 HD (1d8-1 hp + CON) |
| Attack throw | 11+, but no weapon proficiencies: −1, so 12+ | 11+, any weapon and armor |
| Fighting styles | Single weapon | Single, missile, two-handed, weapon & shield |

Both have AC 0, save as F0 (14+ 15+ 16+ 17+ 18+), have no class powers or templates, and start with no
Adventuring proficiency; choose their 4 general proficiencies (plus INT bonus) with `/proficiency add`. The
militia's training is an approximation, so adjust it with `/character training`. At 500 XP,
`/levelup into:Thief` (or another of the 15 **human** classes they qualify for) makes them 1st level, as on
RR p. 313: they gain Adventuring and the class's throws and powers, keep their proficiencies, and re-roll HP
with the new Hit Die, keeping that or their old HP + 1, whichever is higher.

## Animals

Mounts, pack animals, war dogs, and other creatures get their own simple sheets:

- **Stat block**: kind, Hit Dice, HP, AC, attack throw (from Hit Dice unless you set it, per the RR's
  *Attack Throws by Level and HD*), save, morale, special abilities, and notes.
- **Attack routine**: e.g. `attacks:2 hoof 1d6, bite 1d4` on create, or `/animal routine add`.
  `/animal attack` rolls every attack in the routine against the target's AC. Attacks after `or` are
  alternatives made instead of the routine (`2 tusk 2d4 or trample 4d8`); roll one by picking it in `attack`.
- **Load and speed**: everything in the animal's gear counts. `/animal item add` fills in the usual weight
  when you leave `weight` out (as `/item add` does), and homebrew barding weighs like book barding of the
  same AC. Up to its normal load it moves at full
  speed; up to its maximum load, half speed; beyond that it can't move. Tack, saddles, and harness aren't
  enforced: add them (and a rider, at 15 stone plus their gear) as items if you want them counted.
- **Daily needs**: stones of food and water per day (normal load / 10 and / 5 unless the table differs),
  and the cost of working-animal feed at 2 sp per stone.
- **Barding**: `/animal barding material:chain` adds barding with the book's AC (leather +1 to plate +5)
  and weight for the animal's size (man-sized ×2/3, huge ×3, gigantic ×12, colossal ×60), and puts it on.
  `half` halves the weight; `spiked` adds +1 damage per die to its attacks. Homebrew or magic barding:
  `/animal item add barding_ac:…`, then `/animal equip`.
- **Presets**: camel, hunting dog, war dog, donkey, elephant, heavy, light, medium and steppe horses, mule,
  and ox. Speed, loads, food and water come from the Revised Rulebook; AC, Hit Dice, attacks, save, morale,
  senses and proficiencies from the *Monstrous Manual* (an ox is its huge herd animal). Any option you give
  overrides the preset. `war_trained:True` adds +2 morale, plus a second hoof attack for horses (war mules
  and camels get only the morale; donkeys and oxen can't be trained for war). War dogs are already trained.
- **Owner**: set `owner` to a character, and the animal is listed on that character's Inventory page. The
  owner's player (or a Judge) can change the animal; anyone can view it. Animals without an owner belong to
  whoever made them. Deleting a character leaves its animals with no owner.
- **Names** are unique among the server's animals.

Horses and mules from class templates stay as items in the character's inventory; make a sheet for any you
want to track.

## Encounters and initiative

`/encounter start` opens a private two-step setup:

1. **Party**: everyone's active character is pre-ticked; untick absentees, tick extras. Each character's
   initiative bonus comes from their sheet (DEX, Combat Reflexes, Animal Reflexes, Graceful Fighting,
   Fighting Style Specialization, modifiers) and is recalculated every round.
2. **Everyone else**: press **Add combatant** for each monster, NPC, or group: name, initiative modifier, how
   many, enemy or ally, and whether to roll each one separately. By default a group shares one roll, as ACKS
   suggests for identical monsters.

**Roll initiative!** posts the roster in the channel, highest number first, with buttons:
🎲 **Next round** (everyone rolls 1d6 + modifiers again), ➕ **Add**, ➖ **Remove**, 🗑️ **End encounter**.
Ties are marked ⇄ with who chooses the order (same side: they choose; otherwise the smaller side, or the
Judge's side if equal). Combatants added mid-fight roll immediately and join the current round.

There's one roster per channel and it's saved, so it survives a bot restart. Only the Judge or the person who
started the encounter can change it; everyone can see it. To start over, `/encounter end` (or 🗑️) deletes the
roster and `/encounter start` builds a new one. Starting a new one while another is running warns you and
replaces it when you roll.

## Homebrew weapons and armor

Any item can be added, but to equip it as a weapon or armor it needs stats. Either borrow a book item's stats
with `base`, give it its own stats, or both (your stats override the base's):

```
/item add name:Dragon-bone axe damage:1d12 size:large weapon_type:axes
/item add name:Heirloom blade base:Sword damage:1d8/1d10 magic:1
/item add name:Hand cannon damage:2d6 size:missile range:40/80/160
/item add name:Throwing star damage:1d3 size:tiny thrown:True range:20/40/60
/item add name:Mithral shirt armor_ac:5 armor_type:light weight:2 unit:stone
/item add name:Tower shield armor_ac:2 armor_type:shield weight:2 unit:stone
```

- `damage` is dice only: `1d12`, or `1d6/1d8` for one-handed/two-handed (medium weapons). Flat bonuses go in
  `magic` or a `/modifier`.
- `size` decides hands and fighting styles (tiny/small one hand, medium either, large two hands; `missile` for
  bows, slings and guns). `weapon_type` decides class proficiency for classes trained by weapon group, and
  Weapon Focus.
- Classes trained in a fixed list of weapons (mages, crusaders, venturers...) are only proficient with homebrew
  weapons that have a `base` from their list. Otherwise use `/character training add_weapon`, which accepts
  book weapons only, or set `base` to the closest book weapon they know.
- Armor weighs 1 stone per point of AC unless you give a `weight`. `armor_type` decides which classes can wear it.

## Class powers on the sheet

Every class's powers (811 across the 53 classes, including racial traits) are listed with the level they're
gained. The sheet shows the names of the powers the character has now and the next one coming; the **Notes**
page and `/character powers` give a one-line summary of each (`all_levels:True` adds the ones still to come).
Summaries paraphrase the books; check the book for the full rules.

Per-level class skills (thief skills, hiding and sneaking, listening, loremastery, rebuke undead, caster level, dendromancy and crafting rates...) show their current value on the sheet, e.g. *Hiding 8+*.
All class data was cross-checked against the PDFs of all three books: codes of behavior, skill tables and a few summaries were added or corrected; level tables, saves, attack throws, and spell slots matched.

Classes that follow a path (wizard and witch traditions, druid sects, warlock dark paths, earthforger sigils)
only show that path's powers once it's chosen with `/character path`. The sporecaster's optional powers are
listed as choices; record the picks in `/character notes`.

## Proficiencies and class powers that change rolls

Applied automatically: Weapon Finesse, Weapon Focus (extra die on a natural 20), Fighting Style
Specialization (all five styles), Swashbuckling, Combat Reflexes, **Divine Blessing** (+2 saves),
**Combat Ferocity** (+1 cleave), **Running** (+30' speed in medium or lighter armor at 7 stone or less),
Long Range Volleying, Martial Training and Armor Training; class damage bonuses, backstab and ambush,
Animal Reflexes, Graceful Fighting, the pugilist's fists and Legwork, and the fury's Flesh-Runes.

Situational options on the roll commands:

| Option | Effect |
|---|---|
| `raging` (attacks) | Berserkergang: +2 melee/thrown (note: −2 AC). Dwarven fury: Fighting Fury +2 damage |
| `mounted` (attacks) | Mounted Combat: +1 |
| `blind` (attacks) | −4, or −2 with Blind Fighting |
| `foe` (attacks) | Goblin-Slaying / Kin-Slaying (+1, +2 at 7th, +3 at 13th), Vermin-Slaying (+1) |
| `backstab` with Sniping | Backstab or ambush with missiles beyond short range |
| `source` (saves) | Paladin's Aura of Protection +1 vs evil; Vermin-Slaying +1 vs oozes and vermin |
| `agility` (saves) | Acrobatics +2 where agility helps (pit traps, tilting floors) |
| `casting` (initiative) | Battle Magic +1; Combat Reflexes doesn't apply while casting |

Anything else situational (cover, flanking, charging, spells) goes in `situational` or a `/modifier`.
Surprise rolls, thief skills, and other proficiency throws aren't rolled by the bot; use `/throw`.

## What the bot calculates

- **Attack throw** by class progression and level (fighter / thief-crusader / mage tables, plus the demi-human
  tables). A roll hits if **d20 + modifiers ≥ attack throw + target AC**. A natural 20 always hits and a natural 1 always misses.
- **Melee**: STR (or DEX with Weapon Finesse or a bladedancer's power), magic bonus, dual-weapon +1 (+1 more
  with Fighting Style Specialization) plus the off-hand weapon's magic, and your modifiers.
  **Damage**: the weapon's die (1d8 instead of 1d6 for medium weapons held in both hands), STR, the class
  damage bonus by level, magic, and Fighting Style Specialization (two-handed).
- **Missile**: DEX, magic, range penalty, Fighting Style Specialization (missile). Damage adds STR only for
  thrown weapons, and adds the class damage bonus (not for paladins or ruinguards; barbarians choose melee or missile).
- **Backstab / ambush**: +4 to hit, plus the class's extra damage dice (thieves, assassins, and nightblades by
  level; explorers and anyone with Ambushing get +1 die). Missile backstabs only work at short range.
- **Weapon Focus**: a natural 20 with the chosen weapon group adds an extra damage die.
- **Non-proficiency**: armor, weapons, or fighting styles your class can't use make you attack as a 0th-level
  fighter (11+), with no attribute bonuses to attacks or AC and no class powers. The sheet and roll results warn you when this happens.
- **AC**: armor + shield (only for classes with the weapon & shield style) + Fighting Style Specialization +
  DEX + Swashbuckling / Graceful Fighting (light armor and ≤ 5 stone) + modifiers.
- **Saves**: class/level target values; rolls add WIL and any save modifiers.
- **Encumbrance**: every item's weight + coins (1,000 per stone, counted in 1/6-stone steps) → speed band
  (120' / 90' / 60' / 30', overloaded past 20 + STR modifier).

## Notes and limits

- Template gear weights are worked out from the equipment tables. About half match the book's stated
  encumbrance exactly; the rest are within a fraction of a stone, or the book has put rations on a horse. Use
  `/item edit` to adjust anything.
- Situational modifiers the bot can't know about (flanking, cover, charging, Mounted Combat, the paladin's aura
  against evil) go in the `situational` option or a `/modifier`.
- Spells, thief skills, and other class powers are not automated. Keep them in `/character notes`.
- Crusader weapons follow the default worshipper of Ammonar.
- **Supplement classes**: the wizard asks for the book first, then the class. Classes that pick *either*
  dual weapons *or* weapon & shield (courtier, warrior, envoy, oakheart, swordseer) or two of three styles
  (ranger) pick them on the wizard's class step. A Before All Others template that begins with a style
  ("Dual Weapons", "Sentinel (Weapon and Shield)") sets it instead. Change the pick later with
  `/character training style_choice`; characters made before this show a reminder on the sheet. The pugilist's
  fist damage and Legwork AC and the fury's Flesh-Runes AC are applied automatically; spells, spellsinging,
  dendromancy, invocations, and other class powers go in `/character notes`.
- By This Axe's vaultguard and craftpriest are the older ACKS 1e versions of Revised Rulebook classes, so
  the Revised Rulebook versions are used. By This Axe templates don't list encumbrance, so the bot works it out.
- Class data lives in `acks/data/classes/*.json` (one file per book) and can be corrected by hand; the bot
  checks each class when it starts and skips any with missing table values.
- `tools/extract_book_data.py` rebuilds `acks/data/templates.json` and `proficiencies.json` from the
  Markdown export of the rulebook.

## Tests

```bash
python tests/test_rules.py
```

## Licence

- **The bot's code** is released under the MIT License (see [LICENSE](LICENSE)): you may use, modify, and
  share it.
- **The ACKS II game content is not licensed.** The Adventurer Conqueror King System and all rules, tables,
  classes, class powers, templates, proficiencies, spell-slot tables, equipment, and other content from the
  ACKS II Revised Rulebook, Before All Others, and By This Axe are the property of Autarch LLC. They appear here
  (in `acks/data/` and the game tables in `acks/rules.py`) with Autarch LLC's permission; no rights to them are
  granted, and they may not be copied or redistributed except as Autarch LLC allows.
- **Buy the books.** Do not use this bot unless you have purchased the ACKS II source books it draws on from
  [Autarch LLC](https://autarch.co).
