# Adapted from Evenstar-tools/roco-pve-viewer @ 287d335 (MIT).
# Copyright (c) 2026 Evenstar-tools. See LICENSE.upstream.
"""PVE-only state projection; absent values stay unknown."""
from __future__ import annotations
import copy
import json
import math
import re
from pathlib import Path

COMMON_FIELDS = {"conf_id", "base_conf_id", "name", "level", "nature", "height", "weight", "voice", "wear_medal_conf_id", "mutation_type", "blood_id",
                 "changed_nature_pos_attr_type", "changed_nature_neg_attr_type", "nature_attr_change_way"}
INSIDE_FIELDS = {"pet_id", "npc_obj_id", "conf_id", "base_conf_id", "medal_conf_id", "is_player_enemy", "is_entered", "pos"}
ATTRS = {79: "生命", 80: "物攻", 81: "魔攻", 82: "物防", 83: "魔防", 84: "速度"}
PLACEHOLDERS = {9004, 9005, *range(10001, 10023)}
BLOOD_NAMES = {**{i: "普通" for i in range(1, 19)}, 19: "首领", 20: "巨兽", 21: "黑魔法",
               22: "异核", 23: "污染", 24: "奇异"}
BLOOD_FLAGS = {"is_nightmare": "污染", "is_fantastic": "奇异", "is_mixblood": "混血"}
BLOODLINE_RULE = "blood_id_and_reveal_v1"
# The two inspected static catalogs disagree for these forms; neither is verified live.
SIZE_RANGE_CONFLICTS = {3168, 3169, 4094}
SHAPE_RULE = "weight_percent_2_98_v1"
NATURE_RULE = "raw_nature_id_v1"


class Catalog:
    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.species, self.natures, self.medals = data["species"], data["natures"], data["medals"]

    def nature(self, common):
        def raw_uint(key):
            value = common.get(key)
            return value if type(value) is int and 0 <= value <= 0xFFFFFFFF else None

        nature_id = raw_uint("nature")
        original = self.natures.get(str(nature_id), {}) if nature_id else {}
        pos, neg = original.get("positive"), original.get("negative")
        effect_pos, effect_neg = pos, neg
        modified = False
        invalid = False
        for key, which in (("changed_nature_pos_attr_type", "pos"), ("changed_nature_neg_attr_type", "neg")):
            value = raw_uint(key)
            if key in common and (value is None or value > 6):
                invalid = True
            if value is not None and 1 <= value <= 6:
                modified = True
                if which == "pos": effect_pos = value + 78
                else: effect_neg = value + 78
        name = original.get("name", "未知")
        effective = name
        if modified:
            found = next((n for n in self.natures.values() if n["positive"] == effect_pos and n["negative"] == effect_neg), None)
            effective = found["name"] if found else "属性无增减" if effect_pos == effect_neg and effect_pos in ATTRS else "未知"
        if invalid:
            effective = "未知"
        up = down = None
        if pos == neg and pos is not None:
            hint = "属性无增减"
        elif pos in ATTRS and neg in ATTRS:
            hint = f"{ATTRS[pos]}↑ {ATTRS[neg]}↓"
            up, down = ATTRS[pos], ATTRS[neg]
        else:
            hint = "未下发" if not original else ""
        pos_raw, neg_raw, way = (raw_uint(key) for key in
            ("changed_nature_pos_attr_type", "changed_nature_neg_attr_type", "nature_attr_change_way"))
        tip = [f"原始性格：{name}（编号：{nature_id if nature_id is not None else '未下发'}）"]
        if modified or invalid:
            effect_hint = (f"{ATTRS[effect_pos]}↑ {ATTRS[effect_neg]}↓" if not invalid and effect_pos in ATTRS and effect_neg in ATTRS
                           and effect_pos != effect_neg else effective)
            source = {0: "道具", 1: "伙伴"}.get(way, "未下发" if way is None else f"未知编号 {way}")
            tip.extend((f"战斗属性修正：{effect_hint}；对应属性组合：{effective}",
                        f"修正原值：{pos_raw if pos_raw is not None else '未下发'} / {neg_raw if neg_raw is not None else '未下发'}；来源：{source}",
                        "性格名称按原始编号显示，属性修正不覆盖名称"))
        return {"nature": name, "nature_hint": hint, "nature_tip": "\n".join(tip),
                "nature_up": up, "nature_down": down, "nature_id": nature_id,
                "nature_rule": NATURE_RULE, "nature_modified": modified,
                "nature_effective": effective, "nature_pos_raw": pos_raw,
                "nature_neg_raw": neg_raw, "nature_change_way": way}

    def nature_history(self, row):
        row = dict(row)
        if row.get("nature_rule") in (NATURE_RULE, "legacy_original_tip_v1"):
            return row
        old_tip = row.get("nature_tip") if isinstance(row.get("nature_tip"), str) else ""
        match = re.fullmatch(r"原始性格：([^；\r\n]+)(?:；属性经过修正)?", old_tip)
        matches = [(key, value) for key, value in self.natures.items()
                   if match and value.get("name") == match[1]]
        previous = row.get("nature", "未知")
        if len(matches) == 1:
            nature_id, definition = matches[0]
            original = self.nature({"nature": int(nature_id)})
            row.update(original)
            row.update(nature_id=None, nature_rule="legacy_original_tip_v1", nature_modified=None,
                       nature_effective=previous,
                       nature_tip=f"原始性格：{definition['name']}（旧记录文字）\n旧版反查：{previous}\n旧记录未保存性格原值，按原始名称回看")
        else:
            row.update(nature="旧记录待核对", nature_hint="", nature_up=None, nature_down=None,
                       nature_tip=old_tip + "\n旧记录缺少可核对的原始性格，不沿用旧版反查名称")
        return row

    def bloodline(self, pet, common, hidden, shiny):
        raw = common.get("blood_id")
        named = BLOOD_NAMES.get(raw) if type(raw) is int else None
        flags = pet.get("blood_flags", {}) if not hidden else {}
        sources = []
        tips = ["血脉未下发" if raw is None else f"blood_id：{raw}（{named or '未识别'}）"]
        if raw is not None:
            sources.append(pet.get("blood_id_source", "PetData.blood_id"))
        if flags:
            sources.append(pet.get("bloodline_source", "reveal"))
            tips.extend(f"{key}：{'是' if value else '否'}（{BLOOD_FLAGS[key]}）" for key, value in flags.items())
        positive = [label for key, label in BLOOD_FLAGS.items() if flags.get(key) is True]
        # Mixed blood is an additional flag; it has no exclusive raw blood_id here.
        conflict = named and any(key in flags and flags[key] != (named == label)
                                 for key, label in BLOOD_FLAGS.items() if key != "is_mixblood")
        if hidden:
            bloodline = "待揭示"
            tips = ["当前为占位形态或形态编号不一致，等待对应敌方显露"]
            sources = []
        elif conflict:
            bloodline = "待核对"
            tips.append("血脉编号与显露标记不一致，暂不确定血脉")
        else:
            labels = ([named] if named else []) + [label for label in positive if label != named]
            if "普通" in labels and len(labels) > 1:
                labels.remove("普通")
            bloodline = "·".join(labels) if labels else "未知"
            if bloodline == "未知":
                tips.append("缺少可确认血脉的编号或正向显露标记，不推断普通")
        label = bloodline
        if shiny is True:
            label = "异色" if bloodline == "普通" else "异色·" + ("血脉" + bloodline if bloodline in ("未知", "待核对") else bloodline)
        tips.append("异色：" + ("是" if shiny is True else "否" if shiny is False else "未下发"))
        return {"blood_id": raw, "bloodline": bloodline, "bloodline_label": label,
                "bloodline_tip": "\n".join(tips), "bloodline_source": "+".join(sources) or "unknown",
                "bloodline_rule": BLOODLINE_RULE}

    def project(self, pet):
        common, inside = pet["common"], pet["inside"]
        base = common.get("base_conf_id") or inside.get("base_conf_id")
        species = self.species.get(str(base), {})
        hidden = base in PLACEHOLDERS or (common.get("base_conf_id") and inside.get("base_conf_id") and common["base_conf_id"] != inside["base_conf_id"])
        if hidden:
            common = {}
        received_name = common.get("name")
        if not isinstance(received_name, str) or not 0 < len(received_name) <= 80 or not received_name.isprintable():
            received_name = None
        name = "待揭示精灵" if hidden else species.get("name", received_name or (f"精灵 #{base}" if base else "野生精灵"))
        voice = common.get("voice")
        voice_ok = isinstance(voice, (int, float)) and math.isfinite(voice) and -100 <= voice <= 100
        vp = (voice + 100) / 2 if voice_ok else None
        vl = "粗嗓门" if voice_ok and voice <= -96 else "婉转声" if voice_ok and voice >= 96 else "" if voice_ok else "未下发" if voice is None else "数值异常"
        sizes = {}
        default_range = tuple(species.get(k) for k in
                              ("height_low", "height_high", "weight_low", "weight_high")) == (10, 100, 10, 100)
        range_conflict = base in SIZE_RANGE_CONFLICTS
        for key, label, scale, unit in (("height", "身高", 100, "m"), ("weight", "体重", 1000, "kg")):
            raw, low, high = common.get(key), species.get(key + "_low"), species.get(key + "_high")
            evidence = {k: v if type(v) in (int, float) and math.isfinite(v) else None
                        for k, v in (("raw", raw), ("low", low), ("high", high))}
            bounds_ok = all(evidence[k] is not None and evidence[k] > 0 for k in ("low", "high")) and high > low
            pct, hint = None, ""
            tip = [f"精灵：{name}（{base}）"]
            if raw is None:
                hint = "未下发"
                tip.append(f"{label}未下发，暂不计算比例")
            elif evidence["raw"] is None or raw <= 0:
                hint = "数值异常"
                tip.append(f"{label}原值：{raw}；暂不计算比例")
            else:
                tip.append(f"{label}：{raw / scale:g} {unit}（原值 {raw:g}）")
                if range_conflict or default_range:
                    hint = "范围待核对"
                elif not bounds_ok:
                    hint = "范围不可判定"
                elif not low <= raw <= high:
                    hint = "范围待核对"
                    tip.append(f"{label}超出参考范围，暂不计算比例")
                else:
                    pct = (raw - low) / (high - low) * 100
                    # Compare the unrounded weight percentage, matching the original helper.
                    if key == "weight":
                        hint = "小不点" if pct <= 2 else "大块头" if pct >= 98 else ""
            if bounds_ok:
                tip.append(f"参考范围：{low / scale:g}～{high / scale:g} {unit}（原值 {low:g}～{high:g}）")
            else:
                tip.append(f"参考范围原值：{low}～{high}；范围缺失或无效")
            if range_conflict:
                tip.append("该形态的静态范围存在来源冲突，暂不计算身高或体重比例")
            elif default_range:
                tip.append("该形态使用可疑默认范围，暂不计算身高或体重比例")
            if key == "weight":
                tip.append("体重比例≤2%判为小不点，≥98%判为大块头；按未四舍五入的比例判断")
            else:
                tip.append("身高仅显示参考范围中的比例，不用于判定小不点/大块头")
            sizes.update({key: pct, key + "_hint": hint, key + "_tip": "\n".join(tip),
                          **{key + "_" + k: v for k, v in evidence.items()}})
        nature = self.nature(common)
        medal_id = None if hidden else inside.get("medal_conf_id", common.get("wear_medal_conf_id"))
        medal = "未下发" if medal_id is None else "未佩戴" if medal_id == 0 else self.medals.get(str(medal_id), f"奖章 #{medal_id}")
        mutation = common.get("mutation_type")
        revealed = type(mutation) is int and 0 <= mutation <= 0xFFFFFFFF and not mutation & 64
        shiny = bool(mutation & 1) if revealed else None
        fantastic = bool(mutation & 8) if revealed else None
        if not hidden:
            shiny = pet.get("shiny", shiny)
        if shiny is True:
            shiny_hint = "异色·炫彩" if fantastic is True else "异色"
        elif shiny is False:
            shiny_hint = "炫彩（非异色）" if fantastic is True else "非异色"
        else:
            shiny_hint = "炫彩/异色未知" if fantastic is True else "异色未知"
        blood = self.bloodline(pet, common, hidden, shiny)
        return {"id": pet["id"], "name": name, "voice": vp, "voice_hint": vl, **sizes, **blood,
                "base_id": base, "shape_rule": SHAPE_RULE,
                **nature, "medal": medal,
                "shiny": shiny, "fantastic": fantastic, "shiny_hint": shiny_hint,
                "voice_tip": "声音属性在 -100～100 区间的位置" if voice is None else f"声音原值：{voice}",
                "complete": vp is not None and sizes["height"] is not None and sizes["weight"] is not None
                            and nature["nature"] != "未知" and medal_id is not None and shiny is not None
                            and blood["bloodline"] not in ("未知", "待揭示", "待核对")}


class BattleState:
    def __init__(self, catalog):
        self.catalog = catalog
        self.clear("stopped", "已停止", "")

    def clear(self, phase, status, message):
        self.phase, self.status, self.message = phase, status, message
        self.flow, self.battle_id, self.sequence = None, None, None
        self.blocked_battle_id = None
        self.pets = {}
        self.selected = None

    def block(self, flow, message, battle_id=None):
        # Revoke only this encounter; entering another mode must keep earlier wild history.
        revoked = battle_id if flow == self.flow and battle_id == self.battle_id else None
        if self.phase == "blocked" and flow == self.flow:
            revoked = self.blocked_battle_id
        self.clear("blocked", "当前模式已阻断", message)
        self.flow, self.blocked_battle_id = flow, revoked

    def begin_capture(self):
        self.clear("waiting", "等待连接", "读取已开启，请进入游戏世界")

    def on_event(self, event, flow):
        if event == "activity":
            return
        if self.flow is not None and flow != self.flow:
            return
        if event == "pvp_blocked":
            self.block(flow, "玩家 PVP 已阻断，不读取或保存精灵属性", self.battle_id)
            return
        if event == "ready":
            self.clear("waiting", "等待遭遇", "进入野生精灵 PVE 后自动显示")
            return
        if event in ("closed", "reconnect", "gap", "decode_error", "schema_error"):
            if self.phase == "ended" and event == "closed":
                return
            messages = {"closed": ("连接中断", "等待重新连接"), "reconnect": ("连接已重建", "等待野生精灵遭遇"),
                        "gap": ("数据不完整", "请重新进入野生精灵战斗"),
                        "decode_error": ("解码失败", "请重新进入世界；持续失败时需更新协议"),
                        "schema_error": ("协议不匹配", "当前数据未显示，请检查游戏版本")}
            status, message = messages[event]
            self.clear("waiting", status, message)
        elif event == "battle_closed" and self.phase == "active":
            self.phase, self.status = "ended", "战斗已结束"
        elif self.phase == "waiting":
            if event == "missing_key":
                self.status, self.message = "缺少会话信息", "保持读取开启，退出登录界面后重新进入世界"
            elif event == "traffic" and self.status == "等待连接":
                self.status, self.message = "收到游戏流量", "正在等待会话信息"

    def handle(self, flow, opcode, data):
        if opcode == 4886:
            init = data.get("init_info", {})
            if type(data.get("battle_mode")) is not int or data.get("battle_mode") != 1 or not init.get("battle_id"):
                self.block(flow, "仅读取已确认的野生 PVE；PVP 和未知模式已阻断", init.get("battle_id"))
                return
            wrappers = [p for team in init.get("enemy_team", []) for p in team.get("pets", [])]
            # Explicit player markers veto the complete encounter.
            if any(p.get("battle_inside_pet_info", {}).get("is_player_enemy") for p in wrappers):
                self.block(flow, "玩家 PVP 已阻断，不读取或保存精灵属性", init.get("battle_id"))
                return
            self.clear("active", "等待属性", "等待野生精灵属性下发")
            self.flow, self.battle_id = flow, init["battle_id"]
            for team in init.get("enemy_team", []):
                role = team.get("base", {}).get("role_uin")
                for wrapper in team.get("pets", []):
                    inside = wrapper.get("battle_inside_pet_info", {})
                    pid = inside.get("pet_id")
                    if not pid:
                        continue
                    self.pets[pid] = {"id": pid, "common": {}, "inside": {}, "role_uin": role}
                    self.merge(wrapper)
            if self.pets:
                self.selected = next((p["id"] for p in self.pets.values() if p["inside"].get("is_entered")), next(iter(self.pets)))
            return
        if self.phase != "active" or flow != self.flow:
            return
        if opcode == 4908:
            settle = data.get("settle_info", {})
            if settle.get("battle_id") != self.battle_id:
                return
            if settle.get("real_pvp", 0) != 0 or settle.get("real_pve", 1) != 1:
                self.block(flow, "战斗类型不符合野生 PVE，已阻断", self.battle_id)
                return
            for item in settle.get("monster_info", []):
                npc = item.get("npc_obj_id")
                caught = item.get("caught_monster")
                if not npc or not caught:
                    continue
                for pet in self.pets.values():
                    if pet["inside"].get("npc_obj_id") == npc:
                        inside = {"pet_id": pet["id"]}
                        if caught.get("base_conf_id"):
                            inside["base_conf_id"] = caught["base_conf_id"]
                        self.merge({"battle_inside_pet_info": inside, "battle_common_pet_info": caught,
                                    "full_for_data_level": True})
                        if "blood_id" in caught:
                            pet["blood_id_source"] = "settlement:PetData.blood_id"
                        self.apply_reveal_flags(pet["id"], caught.get("season_add_info", {}).get("dice_monster_info", {}), "settlement")
            self.phase, self.status = "ended", "战斗已结束"
            return
        round_state = data.get("state_info", {}) if opcode == 4890 else {}
        if round_state and round_state.get("battle_id") != self.battle_id:
            return
        round_pets = [(wrapper, team.get("base", {}).get("role_uin"))
                      for team in round_state.get("enemy_team", []) for wrapper in team.get("pets", [])]
        cmd = data.get("perform_cmd", {})
        seq = cmd.get("seq_num")
        if seq is not None:
            from .protocol import delta
            if self.sequence is not None and delta(seq, self.sequence) <= 0:
                return
            self.sequence = seq
        # Inspect snapshots and the whole update before merging any attributes.
        if any(p.get("battle_inside_pet_info", {}).get("is_player_enemy") for p, _ in round_pets):
            self.block(flow, "玩家 PVP 已阻断，不读取或保存精灵属性", self.battle_id)
            return
        for info in cmd.get("perform_info", []):
            wrappers = list(info.get("sync_data", {}).get("pet_info", []))
            wrappers.extend(p for p, _ in self.data_update_pets(info))
            branch = {57: "star_transform", 58: "star_shield_break", 59: "dice_shield_break", 60: "dice_mutate"}.get(info.get("type"))
            if branch:
                wrappers.append(info.get(branch, {}).get("pet_info", {}))
            if any(p.get("battle_inside_pet_info", {}).get("is_player_enemy") for p in wrappers):
                self.block(flow, "玩家 PVP 已阻断，不读取或保存精灵属性", self.battle_id)
                return
        # A dice effect may reveal the enemy in the first round snapshot, with
        # no shield-break animation. Its identity still comes from wild entry.
        for wrapper, role in round_pets:
            self.merge_enemy_update(wrapper, role, enemy_side=True)
        for info in cmd.get("perform_info", []):
            for wrapper in info.get("sync_data", {}).get("pet_info", []):
                self.merge(wrapper)
            if info.get("type") == 35:  # BPT_DATA_UPDATE (field number is 44).
                for wrapper, role in self.data_update_pets(info):
                    self.merge_enemy_update(wrapper, role)
            branch = {57: "star_transform", 58: "star_shield_break", 59: "dice_shield_break", 60: "dice_mutate"}.get(info.get("type"))
            if branch and info.get(branch):
                self.merge_reveal(info[branch], branch)

    @staticmethod
    def data_update_pets(info):
        update = info.get("data_update", {})
        pets = [(update["pet"], update.get("uin"))] if update.get("pet") else []
        for key in ("battler", "other"):
            team = update.get(key, {})
            role = team.get("role_uin") if key == "other" else team.get("base", {}).get("role_uin")
            pets.extend((wrapper, role) for wrapper in team.get("pets", []))
        return pets

    def merge_enemy_update(self, wrapper, role=None, *, enemy_side=False):
        inside = wrapper.get("battle_inside_pet_info", {})
        current = self.pets.get(inside.get("pet_id"))
        if current is None:
            return
        registered_role = current.get("role_uin")
        if role is not None and registered_role is not None and role != registered_role:
            return
        npc, registered_npc = inside.get("npc_obj_id"), current["inside"].get("npc_obj_id")
        if npc is not None and registered_npc is not None and npc != registered_npc:
            return
        role_matches = role is not None and role == registered_role
        npc_matches = bool(npc) and npc == registered_npc
        # Generic data_update also carries our own team. A known slot alone is
        # insufficient here; require its registered enemy role or NPC identity.
        if not enemy_side and not (role_matches or npc_matches):
            return
        base = wrapper.get("battle_common_pet_info", {}).get("base_conf_id")
        if base and inside.get("base_conf_id", base) != base:
            return
        if base and "base_conf_id" not in inside:
            wrapper = copy.deepcopy(wrapper)
            wrapper["battle_inside_pet_info"]["base_conf_id"] = base
        self.merge(wrapper)

    def merge_reveal(self, details, source):
        pid = details.get("pet_id")
        if pid not in self.pets or not details.get("pet_info"):
            return
        wrapper = copy.deepcopy(details["pet_info"])
        inside = wrapper.setdefault("battle_inside_pet_info", {})
        if inside.get("is_player_enemy"):
            self.block(self.flow, "玩家 PVP 已阻断，不读取或保存精灵属性", self.battle_id)
            return
        common = wrapper.get("battle_common_pet_info", {})
        base = common.get("base_conf_id")
        current = self.pets[pid]
        old_base = current["inside"].get("base_conf_id") or current["common"].get("base_conf_id")
        if (not base or inside.get("pet_id", pid) != pid or inside.get("base_conf_id", base) != base
                or details.get("base_conf_id", base) != base or inside.get("is_player_enemy")):
            return
        if "conf_id" in inside and "conf_id" in common and inside["conf_id"] != common["conf_id"]:
            return
        old_field = "old_base_id" if source == "star_transform" else "old_base_conf_id"
        if old_field in details and old_base not in (details[old_field], base):
            return
        npc = inside.get("npc_obj_id")
        registered_npc = current["inside"].get("npc_obj_id")
        if npc is not None and registered_npc is not None and npc != registered_npc:
            return
        inside.setdefault("pet_id", pid)
        inside.setdefault("base_conf_id", base)
        wrapper["full_for_data_level"] = True
        self.merge(wrapper)
        if "blood_id" in common:
            self.pets[pid]["blood_id_source"] = source + ":PetData.blood_id"
        # DiceMutate.mutation_type is PetMutationType, not the PetData bitmask.
        if source in ("star_shield_break", "dice_shield_break"):
            self.apply_reveal_flags(pid, details, source)

    def apply_reveal_flags(self, pid, details, source):
        pet = self.pets.get(pid)
        if not pet:
            return
        base = pet["common"].get("base_conf_id") or pet["inside"].get("base_conf_id")
        if (not base or base in PLACEHOLDERS or pet["inside"].get("base_conf_id", base) != base
                or details.get("base_conf_id", base) not in (0, base)):
            return
        # is_fantastic is 奇异血脉 here; only PetData mutation bit 8 means 炫彩.
        shiny = details.get("is_shiny")
        if type(shiny) is bool:
            pet["shiny"] = shiny
        for field in BLOOD_FLAGS:
            value = details.get(field)
            if type(value) is bool:
                pet.setdefault("blood_flags", {})[field] = value
                pet["bloodline_source"] = source
        mixed = details.get("mix_blood")
        if source == "settlement" and type(mixed) is int and mixed >= 0:
            pet.setdefault("blood_flags", {})["is_mixblood"] = mixed > 0
            pet["bloodline_source"] = source

    def merge(self, wrapper):
        inside = wrapper.get("battle_inside_pet_info", {})
        if inside.get("is_player_enemy"):
            self.block(self.flow, "玩家 PVP 已阻断，不读取或保存精灵属性", self.battle_id)
            return
        pid = inside.get("pet_id")
        if pid not in self.pets:
            # Never learn enemy identity from generic syncs, which also contain the player's pets.
            return
        pet = self.pets[pid]
        common = wrapper.get("battle_common_pet_info", {})
        new_base = inside.get("base_conf_id") or common.get("base_conf_id")
        old_base = pet["inside"].get("base_conf_id") or pet["common"].get("base_conf_id")
        if (new_base and old_base and new_base != old_base) or wrapper.get("full_for_data_level"):
            pet["common"] = {}
            pet.pop("shiny", None)
            pet.pop("blood_flags", None)
            pet.pop("bloodline_source", None)
            pet.pop("blood_id_source", None)
            # A form replacement must not retain the former form's medal.
            if new_base and old_base and new_base != old_base:
                pet["inside"].pop("medal_conf_id", None)
        if "mutation_type" in common:
            pet.pop("shiny", None)
        if "blood_id" in common:
            pet.pop("blood_flags", None)
            pet.pop("bloodline_source", None)
            pet.pop("blood_id_source", None)
        pet["inside"].update({k: v for k, v in inside.items() if k in INSIDE_FIELDS})
        pet["common"].update({k: v for k, v in common.items() if k in COMMON_FIELDS})

    def snapshot(self):
        views = [self.catalog.project(p) for p in self.pets.values()]
        selected = next((p for p in views if p["id"] == self.selected), views[0] if views else None)
        status = self.status
        if self.phase == "active" and selected:
            status = "已读取" if selected["complete"] else "部分已读取"
        return {"phase": self.phase, "status": status, "message": self.message, "pets": views,
                "selected": selected, "battle_id": self.battle_id,
                "blocked_battle_id": self.blocked_battle_id}
