#!/usr/bin/env python3
"""Initialize, upsert, and read the QuantTide Public Member Index Feishu Bitable (多维表格).

Supports four modes via the student's local `lark-cli` (zero Git/GitHub required):
  - `--mode init`:   Create a new Feishu Bitable public index (`成员协作主页索引` table +
                     grid & gallery views) with structured cross-host schema (`qt-public-index/v2`).
  - `--mode upsert`: Register or update ONLY the current member's single row record
                     (`lark-cli base +record-upsert` matched by `成员键` = `open_id`),
                     ensuring atomic row-level updates with zero concurrent clobbering.
  - `--mode list`:   Fetch all member records from the Bitable as clean structured JSON
                     (ready for peer-buddy matching and coordination-pulse skills).
  - `--mode share`:  Update link-sharing permission on the Bitable (requires `--confirm-share`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

# Default QuantTide Public Member Index Feishu Bitable (can be overridden via
# --registry-base, career-discovery/.card-link.json, or QT_PUBLIC_INDEX_BASE).
DEFAULT_REGISTRY_BASE = "VG9mbW3TGa2nFdsWUDfcZEEYnMj"
DEFAULT_REGISTRY_TABLE = "tblRa7hYNcFA0GJq"
DEFAULT_REGISTRY_URL = "https://vcnrx885ykp1.feishu.cn/base/VG9mbW3TGa2nFdsWUDfcZEEYnMj"
SCHEMA_VERSION = "qt-public-index/v2-bitable"

TABLE_FIELDS_SCHEMA: list[dict[str, Any]] = [
    {
        "name": "成员键",
        "type": "text",
        "description": "唯一索引键（优先飞书 open_id），供个人 AI 幂等原位更新",
    },
    {
        "name": "成员",
        "type": "user",
        "multiple": False,
        "description": "飞书头像与实名，点击即可一键私聊",
    },
    {
        "name": "个人主页",
        "type": "text",
        "style": {"type": "url"},
        "description": "Bento 个人协作主页固定链接",
    },
    {
        "name": "协作状态",
        "type": "select",
        "multiple": False,
        "options": [
            {"name": "寻找搭档"},
            {"name": "单兵推进"},
            {"name": "可顺手答疑"},
            {"name": "阶段静默"},
        ],
    },
    {"name": "一句话搭伙切口", "type": "text"},
    {"name": "Offer（我能兜底）", "type": "text"},
    {"name": "Seek（想找同路人）", "type": "text"},
    {"name": "Avoid（协作边界）", "type": "text"},
    {"name": "投入节奏与时段", "type": "text"},
    {"name": "2周微实验", "type": "text"},
    {
        "name": "Playbooks（进展与经验）",
        "type": "text",
        "description": "近期跑通的小成果或可复用踩坑经验，供同伴 AI 检索请教对象",
    },
    {
        "name": "Active-Blockers（活跃困惑）",
        "type": "text",
        "description": "当前卡点（建议格式：[B-YYYYMMDD-01｜OPEN] 具体卡点）",
    },
    {
        "name": "更新时间",
        "type": "text",
        "description": "最近一次同步日期 YYYY-MM-DD",
    },
]


def find_lark_cli() -> str | None:
    for candidate in (
        Path.home() / ".local" / "bin" / "lark-cli",
        Path.home() / ".homebrew" / "bin" / "lark-cli",
        Path("/opt/homebrew/bin/lark-cli"),
        Path("/usr/local/bin/lark-cli"),
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("lark-cli")


def run_cmd(
    cmd: list[str], timeout: int = 90, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.setdefault("LARK_CLI_NO_PROXY_WARN", "1")
    return subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=str(cwd) if cwd else None,
        check=False,
    )


def extract_base_token(base_ref: str) -> str:
    raw = (base_ref or "").strip()
    if not raw:
        return ""
    m = re.search(r"/(?:base|bitable)/([A-Za-z0-9_-]+)", raw)
    if m:
        return m.group(1)
    return raw


def get_feishu_identity(lark_bin: str) -> tuple[str, str]:
    proc = run_cmd([lark_bin, "whoami"], timeout=15)
    if proc.returncode == 0:
        try:
            payload = json.loads(proc.stdout)
            behalf = payload.get("onBehalfOf") or {}
            open_id = str(behalf.get("openId") or "").strip()
            user_name = str(behalf.get("userName") or "").strip()
            return open_id, user_name
        except json.JSONDecodeError:
            pass
    return "", ""


def strip_md_inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()


def parse_partner_card_md(md_text: str) -> dict[str, str]:
    parsed = {
        "intro": "",
        "offer": "",
        "avoid": "",
        "seek": "",
        "weekly_budget": "",
        "schedule_blackout": "",
        "experiment": "",
        "playbooks": "",
        "active_blockers": "",
        "generated_at": dt.date.today().isoformat(),
        "schema_version": "qt-partner-card/v1.1",
    }

    section = ""
    intro_lines: list[str] = []
    exp_lines: list[str] = []

    for raw in md_text.splitlines():
        line = raw.strip()
        if not line or line == "---":
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if "怎么搭伙" in heading or "一句话" in heading:
                section = "intro"
            elif "协作接口" in heading:
                section = "interface"
            elif "实验" in heading or "自述" in heading or "短帖" in heading:
                section = "experiment"
            elif "动态脉冲" in heading or "脉冲" in heading or "活跃困惑" in heading:
                section = "pulse"
            else:
                section = ""
            continue

        if line.startswith("Generated-At:"):
            parsed["generated_at"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("Schema-Version:"):
            parsed["schema_version"] = line.split(":", 1)[1].strip()
            continue

        m = re.match(r"^-\s*\*\*([^*]+)\*\*[:：]\s*(.+)$", line)
        if m:
            key_raw, val_raw = m.group(1), strip_md_inline(m.group(2))
            if "Offer" in key_raw:
                parsed["offer"] = val_raw
            elif "Avoid" in key_raw:
                parsed["avoid"] = val_raw
            elif "Seek" in key_raw:
                parsed["seek"] = val_raw
            elif "Weekly-Budget" in key_raw:
                parsed["weekly_budget"] = val_raw
            elif "Schedule-Blackout" in key_raw:
                parsed["schedule_blackout"] = val_raw
            elif "Playbooks" in key_raw or "进展" in key_raw or "可复用经验" in key_raw:
                parsed["playbooks"] = val_raw
            elif "Active-Blockers" in key_raw or "活跃困惑" in key_raw or "当前困惑" in key_raw:
                parsed["active_blockers"] = val_raw
            continue

        clean = strip_md_inline(line.lstrip("> ").strip())
        if section == "intro":
            intro_lines.append(clean)
        elif section == "experiment":
            exp_lines.append(clean)

    parsed["intro"] = " ".join(intro_lines).strip()
    parsed["experiment"] = " ".join(exp_lines).strip()
    return parsed


def apply_feishu_share(lark_bin: str, base_token: str, share: str) -> tuple[str, str | None]:
    if share == "none":
        return "private_owner_only", None

    params = json.dumps({"token": base_token, "type": "bitable"}, ensure_ascii=False)
    desired_external = share in ("anyone_readable", "anyone_editable")
    data = json.dumps(
        {
            "external_access": desired_external,
            "link_share_entity": share,
        },
        ensure_ascii=False,
    )
    proc = run_cmd(
        [
            lark_bin,
            "drive",
            "permission.public",
            "patch",
            "--as",
            "user",
            "--params",
            params,
            "--data",
            data,
            "--yes",
        ]
    )
    if proc.returncode == 0:
        return share, None
    return "permission_unchanged", (proc.stderr or proc.stdout).strip()[:240]


def init_registry_base(
    lark_bin: str,
    title: str,
    table_name: str,
    share: str,
    confirm_share: bool,
    state_path: Path | None = None,
) -> dict[str, Any]:
    crt = run_cmd(
        [
            lark_bin,
            "base",
            "+base-create",
            "--as",
            "user",
            "--name",
            title,
            "--time-zone",
            "Asia/Shanghai",
            "--table-name",
            table_name,
            "--fields",
            json.dumps(TABLE_FIELDS_SCHEMA, ensure_ascii=False),
        ]
    )
    if crt.returncode != 0:
        return {
            "status": "error",
            "action": "init",
            "error": (crt.stderr or crt.stdout).strip()[:400],
        }

    payload = json.loads(crt.stdout)
    data = payload.get("data") or {}
    base_info = data.get("base") or {}
    table_info = data.get("table") or {}
    base_token = str(base_info.get("base_token") or "")
    url = str(base_info.get("url") or "")
    table_id = str(table_info.get("id") or "")
    if not base_token or not table_id:
        return {"status": "error", "action": "init", "error": "missing_base_or_table_id_in_response"}

    # Add a gallery card view for comfortable long-text browsing alongside the grid view
    run_cmd(
        [
            lark_bin,
            "base",
            "+view-create",
            "--as",
            "user",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--json",
            json.dumps({"name": "搭档名片墙", "type": "gallery"}, ensure_ascii=False),
        ]
    )

    applied_share = "private_owner_only"
    share_warn = None
    if confirm_share and share != "none":
        applied_share, share_warn = apply_feishu_share(lark_bin, base_token, share)

    result = {
        "status": "ok",
        "action": "created_public_index_bitable",
        "schema_version": SCHEMA_VERSION,
        "registry_base_token": base_token,
        "registry_table_id": table_id,
        "registry_url": url,
        "share": applied_share,
        "warning": share_warn,
    }
    if state_path:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if state_path.is_file():
            try:
                loaded = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            except json.JSONDecodeError:
                pass
        existing["registry_base_token"] = base_token
        existing["registry_table_id"] = table_id
        existing["registry_url"] = url
        existing["registry_share"] = applied_share
        state_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _parse_bitable_json_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    fields = data.get("fields") or []
    records = data.get("data") if isinstance(data.get("data"), list) else (data.get("records") or [])
    record_ids = data.get("record_id_list") or []

    parsed: list[dict[str, Any]] = []
    # Shape 1: matrix form (fields: [...], data/records: [[...]], record_id_list: [...])
    if isinstance(fields, list) and fields and isinstance(records, list) and (
        not records or isinstance(records[0], list)
    ):
        for idx, row in enumerate(records):
            rec_id = record_ids[idx] if idx < len(record_ids) else ""
            row_map: dict[str, Any] = {"record_id": rec_id}
            for col_idx, col_name in enumerate(fields):
                row_map[str(col_name)] = row[col_idx] if col_idx < len(row) else None
            parsed.append(row_map)
        return parsed

    # Shape 2: list of dicts ({record_id, fields: {...}} or flat dicts)
    if isinstance(records, list):
        for item in records:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("fields"), dict):
                row_map = {"record_id": str(item.get("record_id") or item.get("id") or "")}
                row_map.update(item["fields"])
                parsed.append(row_map)
            else:
                parsed.append(dict(item))
    return parsed


def list_registry_members(
    lark_bin: str, base_token: str, table_id: str
) -> dict[str, Any]:
    token = extract_base_token(base_token)
    if not token:
        return {"status": "error", "error": "missing_registry_base_token"}
    proc = run_cmd(
        [
            lark_bin,
            "base",
            "+record-list",
            "--as",
            "user",
            "--base-token",
            token,
            "--table-id",
            table_id,
            "--format",
            "json",
            "--limit",
            "200",
        ],
        timeout=30,
    )
    if proc.returncode != 0:
        return {"status": "error", "error": (proc.stderr or proc.stdout).strip()[:400]}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "error": "invalid_json_from_record_list"}

    rows = _parse_bitable_json_records(payload)
    members: list[dict[str, Any]] = []
    for row in rows:
        user_cell = row.get("成员")
        open_id = str(row.get("成员键") or "").strip()
        user_name = ""
        if isinstance(user_cell, list) and user_cell:
            first_u = user_cell[0]
            if isinstance(first_u, dict):
                if not open_id:
                    open_id = str(first_u.get("id") or "")
                user_name = str(first_u.get("name") or "")
        raw_url = str(row.get("个人主页") or "")
        m_md_url = re.match(r"^\[[^\]]*\]\((https?://[^)]+)\)$", raw_url.strip())
        clean_url = m_md_url.group(1) if m_md_url else raw_url
        raw_status = row.get("协作状态")
        clean_status = raw_status[0] if isinstance(raw_status, list) and raw_status else (raw_status or "")
        members.append(
            {
                "record_id": str(row.get("record_id") or ""),
                "member_key": open_id,
                "user_name": user_name,
                "homepage_url": clean_url,
                "status": clean_status,
                "intro": str(row.get("一句话搭伙切口") or ""),
                "offer": str(row.get("Offer（我能兜底）") or ""),
                "seek": str(row.get("Seek（想找同路人）") or ""),
                "avoid": str(row.get("Avoid（协作边界）") or ""),
                "rhythm": str(row.get("投入节奏与时段") or ""),
                "experiment": str(row.get("2周微实验") or ""),
                "playbooks": str(row.get("Playbooks（进展与经验）") or ""),
                "active_blockers": str(row.get("Active-Blockers（活跃困惑）") or ""),
                "updated_at": str(row.get("更新时间") or ""),
            }
        )
    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "registry_base_token": token,
        "registry_table_id": table_id,
        "member_count": len(members),
        "members": members,
    }


def upsert_member_to_registry(
    lark_bin: str,
    base_token: str,
    table_id: str,
    card_path: Path,
    homepage_url: str = "",
    homepage_doc_id: str = "",
    collab_status: str = "寻找搭档",
) -> dict[str, Any]:
    token = extract_base_token(base_token)
    if not token:
        return {"status": "error", "error": "missing_registry_base_token"}
    if not card_path.is_file():
        return {"status": "error", "error": f"card_not_found:{card_path}"}

    open_id, user_name = get_feishu_identity(lark_bin)
    fields = parse_partner_card_md(card_path.read_text(encoding="utf-8"))
    updated_at = dt.date.today().isoformat()
    member_key = open_id or (f"doc:{homepage_doc_id}" if homepage_doc_id else user_name or "member")

    # Find existing record_id by member_key (or matching user open_id)
    listed = list_registry_members(lark_bin, token, table_id)
    if listed.get("status") != "ok":
        return {"status": "error", "error": f"list_registry_failed:{listed.get('error')}"}

    existing_record_id = ""
    for m in listed.get("members") or []:
        if m.get("member_key") == member_key:
            existing_record_id = str(m.get("record_id") or "")
            break

    rhythm_parts = [p for p in (fields.get("weekly_budget"), fields.get("schedule_blackout")) if p]
    record_fields: dict[str, Any] = {
        "成员键": member_key,
        "协作状态": [collab_status],
        "一句话搭伙切口": fields.get("intro") or "",
        "Offer（我能兜底）": fields.get("offer") or "",
        "Seek（想找同路人）": fields.get("seek") or "",
        "Avoid（协作边界）": fields.get("avoid") or "",
        "投入节奏与时段": "｜".join(rhythm_parts),
        "2周微实验": fields.get("experiment") or "",
        "Playbooks（进展与经验）": fields.get("playbooks") or "暂无（待日常反思补充）",
        "Active-Blockers（活跃困惑）": fields.get("active_blockers") or "暂无挂出困惑",
        "更新时间": updated_at,
    }
    if open_id.startswith("ou_"):
        record_fields["成员"] = [{"id": open_id}]
    if homepage_url:
        record_fields["个人主页"] = homepage_url

    cmd = [
        lark_bin,
        "base",
        "+record-upsert",
        "--as",
        "user",
        "--base-token",
        token,
        "--table-id",
        table_id,
        "--json",
        json.dumps(record_fields, ensure_ascii=False),
    ]
    if existing_record_id:
        cmd.extend(["--record-id", existing_record_id])
        action = "updated_member_record_in_place"
    else:
        action = "created_member_record"

    upd = run_cmd(cmd)
    if upd.returncode != 0:
        return {
            "status": "error",
            "action": action,
            "error": (upd.stderr or upd.stdout).strip()[:400],
        }

    final_record_id = existing_record_id
    try:
        resp = json.loads(upd.stdout)
        rec = ((resp.get("data") or {}).get("record")) or resp.get("data") or {}
        final_record_id = str(rec.get("record_id") or rec.get("id") or final_record_id)
    except json.JSONDecodeError:
        pass
    if not final_record_id:
        post_list = list_registry_members(lark_bin, token, table_id)
        for m in post_list.get("members") or []:
            if m.get("member_key") == member_key:
                final_record_id = str(m.get("record_id") or "")
                break

    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "action": action,
        "registry_base_token": token,
        "registry_table_id": table_id,
        "registry_url": f"https://vcnrx885ykp1.feishu.cn/base/{token}" if token == DEFAULT_REGISTRY_BASE else "",
        "record_id": final_record_id,
        "member_key": member_key,
        "member_name": user_name,
        "updated_at": updated_at,
    }


def resolve_registry_target(
    cli_base: str, cli_table: str, state_path: Path | None
) -> tuple[str, str]:
    base_token = extract_base_token(cli_base)
    table_id = (cli_table or "").strip()

    if state_path and state_path.is_file():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if not base_token and data.get("registry_base_token"):
                    base_token = extract_base_token(str(data["registry_base_token"]))
                if not table_id and data.get("registry_table_id"):
                    table_id = str(data["registry_table_id"]).strip()
        except json.JSONDecodeError:
            pass

    if not base_token:
        base_token = extract_base_token(os.environ.get("QT_PUBLIC_INDEX_BASE", "")) or DEFAULT_REGISTRY_BASE
    if not table_id:
        table_id = os.environ.get("QT_PUBLIC_INDEX_TABLE", "").strip() or DEFAULT_REGISTRY_TABLE
    return base_token, table_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("init", "upsert", "list", "share"),
        required=True,
        help="init: create a new Bitable public index; upsert: create/update current member's row; list: parse all rows as JSON; share: update permission.",
    )
    parser.add_argument(
        "--registry-base",
        "--registry-doc",
        dest="registry_base",
        default="",
        help="Target Feishu Bitable base token or URL (defaults to QuantTide public index Bitable).",
    )
    parser.add_argument(
        "--table-id",
        default="",
        help="Target table ID or name in the Bitable (defaults to 成员协作主页索引).",
    )
    parser.add_argument(
        "--card",
        type=Path,
        default=Path("career-discovery/partner-card.md"),
        help="Path to local partner-card.md (for --mode upsert).",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=Path("career-discovery/.card-link.json"),
        help="Path to local .card-link.json storing homepage URL/doc_id and registry metadata.",
    )
    parser.add_argument(
        "--collab-status",
        choices=("寻找搭档", "单兵推进", "可顺手答疑", "阶段静默"),
        default="寻找搭档",
        help="Collaboration status tag for --mode upsert.",
    )
    parser.add_argument(
        "--title",
        default="量潮实训基地｜成员协作主页与动态检索目录",
        help="Base name for --mode init.",
    )
    parser.add_argument(
        "--table-name",
        default="成员协作主页索引",
        help="First table name for --mode init.",
    )
    parser.add_argument(
        "--share",
        choices=("none", "tenant_readable", "tenant_editable", "anyone_readable", "anyone_editable"),
        default="none",
        help="Permission level for --mode init or --mode share (applied ONLY when --confirm-share is passed).",
    )
    parser.add_argument(
        "--confirm-share",
        action="store_true",
        help="Pass ONLY after the user explicitly confirms changing link-sharing permissions.",
    )
    parser.add_argument(
        "--confirm-registry",
        action="store_true",
        help="Required consent gate for --mode upsert so a student's card is never pushed publicly without confirmation.",
    )
    args = parser.parse_args()

    lark_bin = find_lark_cli()
    if not lark_bin:
        print(json.dumps({"status": "unavailable", "reason": "lark_cli_not_found"}, ensure_ascii=False))
        return 0

    if args.mode == "init":
        res = init_registry_base(
            lark_bin=lark_bin,
            title=args.title,
            table_name=args.table_name,
            share=args.share,
            confirm_share=args.confirm_share,
            state_path=args.state,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["status"] == "ok" else 1

    base_token, table_id = resolve_registry_target(args.registry_base, args.table_id, args.state)

    if args.mode == "share":
        if not args.confirm_share or args.share == "none":
            print(
                json.dumps(
                    {
                        "status": "error",
                        "reason": "missing_share_confirmation",
                        "message": "Pass --share <level> and --confirm-share only after explicit user confirmation.",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        applied, warn = apply_feishu_share(lark_bin, base_token, args.share)
        ok = applied == args.share
        print(
            json.dumps(
                {
                    "status": "ok" if ok else "error",
                    "registry_base_token": base_token,
                    "share": applied,
                    "warning": warn,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if ok else 1

    if args.mode == "list":
        res = list_registry_members(lark_bin, base_token, table_id)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["status"] == "ok" else 1

    # --mode upsert
    if not args.confirm_registry:
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "missing_user_consent",
                    "message": "Pass --confirm-registry only after the student explicitly agrees to sync their card to the public index.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    homepage_url = ""
    homepage_doc_id = ""
    if args.state.is_file():
        try:
            st = json.loads(args.state.read_text(encoding="utf-8"))
            if isinstance(st, dict):
                homepage_url = str(st.get("feishu_url") or "")
                homepage_doc_id = str(st.get("feishu_doc_id") or "")
        except json.JSONDecodeError:
            pass

    res = upsert_member_to_registry(
        lark_bin=lark_bin,
        base_token=base_token,
        table_id=table_id,
        card_path=args.card,
        homepage_url=homepage_url,
        homepage_doc_id=homepage_doc_id,
        collab_status=args.collab_status,
    )
    if res.get("status") == "ok" and args.state:
        existing: dict[str, Any] = {}
        if args.state.is_file():
            try:
                loaded = json.loads(args.state.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            except json.JSONDecodeError:
                pass
        existing["registry_base_token"] = res["registry_base_token"]
        existing["registry_table_id"] = res["registry_table_id"]
        existing["registry_record_id"] = res.get("record_id", "")
        if res.get("registry_url"):
            existing["registry_url"] = res["registry_url"]
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
