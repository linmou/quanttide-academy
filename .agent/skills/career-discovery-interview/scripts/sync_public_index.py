#!/usr/bin/env python3
"""Initialize, upsert, and read the QuantTide Public Member Index Feishu Cloud Doc.

Supports three modes via the student's local `lark-cli` (zero Git/GitHub required):
  - `--mode init`:   Create a new Feishu Cloud Doc public index with contract notes,
                     cross-host schema conventions (`qt-public-index/v1`), and member directory.
  - `--mode upsert`: Register or update ONLY the current member's single `<callout>` block
                     in-place (`block_replace` when found, `append` when new), never
                     overwriting other members' cards.
  - `--mode list`:   Fetch the public index doc and parse all member cards into structured JSON
                     (ready for peer-buddy matching and coordination-pulse skills).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# Default QuantTide public index Feishu doc token (can be overridden via
# --registry-doc, career-discovery/.card-link.json, or QT_PUBLIC_INDEX_DOC).
DEFAULT_REGISTRY_DOC = "W90qdp8azogcCZxCNGfcEEWonuc"
DEFAULT_REGISTRY_URL = "https://vcnrx885ykp1.feishu.cn/docx/W90qdp8azogcCZxCNGfcEEWonuc"
SCHEMA_VERSION = "qt-public-index/v1"


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


def xml_esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def extract_doc_token(doc_ref: str) -> str:
    raw = (doc_ref or "").strip()
    if not raw:
        return ""
    m = re.search(r"/(?:docx|docs|wiki)/([A-Za-z0-9_-]+)", raw)
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


def build_index_init_xml(title: str) -> str:
    today = dt.date.today().isoformat()
    return f"""<title>{xml_esc(title)}</title>
<callout emoji="🧭" background-color="light-blue" border-color="blue">
  <p><b>量潮实训基地去中心化协作网络 · 统一公共检索入口</b>（<code>{SCHEMA_VERSION}</code> · 创建于 {today}）</p>
  <p><b>数据主权契约</b>：本目录仅收录成员经个人 AI 梳理、<b>经本人确认自愿公开</b>的协作摘要与个人主页链接；所有原始访谈对话与本地私享档案（<code>career-discovery/profile.md</code>）均留在成员本地电脑，组织不监控、不调阅。</p>
  <p><b>使用方式</b>：① <b>人找搭档</b>：直接浏览下方成员名片，点击飞书头像一键发起私聊，或点击主页链接查看完整 Bento 名片；② <b>个人 AI 挂接与巡检</b>：每位成员占一张独立名片卡片，个人 AI 仅原位更新属于自己的单张卡片，绝不覆盖他人内容。</p>
</callout>
<h2>跨宿主字段与状态约定（供个人 AI 稳定解析）</h2>
<table>
  <colgroup><col width="180"/><col width="280"/><col width="320"/></colgroup>
  <thead>
    <tr>
      <th background-color="light-gray"><p><b>标准字段</b></p></th>
      <th background-color="light-gray"><p><b>内容含义</b></p></th>
      <th background-color="light-gray"><p><b>协作与 AI 巡检用途</b></p></th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><p><b>Offer（我能兜底）</b></p></td>
      <td><p>当前最顺手的长板与愿意提供的帮助</p></td>
      <td><p>供给侧标签：当同伴挂出相关困惑时触发双向撮合</p></td>
    </tr>
    <tr>
      <td><p><b>Seek（想找同路人）</b></p></td>
      <td><p>希望互补的能力类型与合作切口</p></td>
      <td><p>需求侧标签：匹配互补搭档与 2 周微实验同路人</p></td>
    </tr>
    <tr>
      <td><p><b>Avoid（协作边界）</b></p></td>
      <td><p>中性脱敏后的拒绝事项与合作红线</p></td>
      <td><p>前置排雷：降低磨合摩擦，防止工具人消耗</p></td>
    </tr>
    <tr>
      <td><p><b>Playbooks（进展与经验）</b></p></td>
      <td><p>近期跑通的小成果或可复用踩坑经验</p></td>
      <td><p>动态供给：供其他成员的个人 AI 检索请教对象</p></td>
    </tr>
    <tr>
      <td><p><b>Active-Blockers（活跃困惑）</b></p></td>
      <td><p>当前卡点（建议格式：<code>[B-YYYYMMDD-01｜OPEN] 具体卡点</code>）</p></td>
      <td><p>动态需求：触发同伴顺手解答、互助确认与超时例外兜底</p></td>
    </tr>
  </tbody>
</table>
<h2>成员协作主页索引目录</h2>
<p>以下每张灰色卡片对应一位成员的公开摘要（单块原子维护）。新成员通过 <code>career-discovery-interview</code> 发布个人主页并确认同步后，将自动追加至此目录末尾；再次更新时自动原位刷新本人卡片。</p>
"""


def truncate_one_line(text: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", (text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def build_member_callout_xml(
    fields: dict[str, str],
    open_id: str,
    user_name: str,
    homepage_url: str,
    homepage_doc_id: str,
    updated_at: str,
) -> str:
    if open_id.startswith("ou_"):
        member_cite = f'<cite type="user" user-id="{xml_esc(open_id)}"/>'
        member_key = f"id:{open_id}"
    else:
        member_cite = f"<b>{xml_esc(user_name or '基地成员')}</b>"
        member_key = f"doc:{homepage_doc_id}" if homepage_doc_id else f"name:{user_name or 'member'}"

    if homepage_url:
        homepage_link = f'<a href="{xml_esc(homepage_url)}">查看完整 Bento 个人主页</a>'
    elif homepage_doc_id:
        homepage_link = f'<cite type="doc" doc-id="{xml_esc(homepage_doc_id)}"/>'
    else:
        homepage_link = "本地名片（暂未发布云文档）"

    intro = truncate_one_line(fields.get("intro") or "欢迎直接私聊对齐 2 周小实验切口。", 180)
    offer = truncate_one_line(fields.get("offer") or "待补充", 220)
    seek = truncate_one_line(fields.get("seek") or "待补充", 220)
    avoid = truncate_one_line(fields.get("avoid") or "待补充", 220)
    budget = truncate_one_line(fields.get("weekly_budget") or "未标注", 80)
    blackout = truncate_one_line(fields.get("schedule_blackout") or "未标注", 120)
    experiment = truncate_one_line(fields.get("experiment") or "见个人主页 2 周微实验", 220)
    playbooks = truncate_one_line(fields.get("playbooks") or "暂无（待日常反思补充）", 220)
    blockers = truncate_one_line(fields.get("active_blockers") or "暂无挂出困惑", 220)

    return f"""<callout emoji="🪪" background-color="light-gray" border-color="gray">
  <p><b>成员</b>：{member_cite} ｜ <b>个人主页</b>：{homepage_link} ｜ <b>更新</b>：{xml_esc(updated_at)} ｜ <code>{xml_esc(member_key)}</code></p>
  <p><b>一句话搭伙切口</b>：{xml_esc(intro)}</p>
  <p><b>⚡ Offer（我能兜底）</b>：{xml_esc(offer)}<br/><b>🧭 Seek（想找同路人）</b>：{xml_esc(seek)}<br/><b>🛡 Avoid（协作边界）</b>：{xml_esc(avoid)}<br/><b>⏱ 投入节奏与时段</b>：{xml_esc(budget)}｜{xml_esc(blackout)}</p>
  <p><b>🚀 2 周微实验</b>：{xml_esc(experiment)}<br/><b>🧩 进展与可复用经验（Playbooks）</b>：{xml_esc(playbooks)}<br/><b>❓ 当前活跃困惑（Active-Blockers）</b>：{xml_esc(blockers)}</p>
</callout>"""


def apply_feishu_share(lark_bin: str, doc_id: str, share: str) -> tuple[str, str | None]:
    if share == "none":
        return "private_owner_only", None

    params = json.dumps({"token": doc_id, "type": "docx"}, ensure_ascii=False)
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


def fetch_doc_xml(lark_bin: str, doc_id: str) -> tuple[str | None, int | None, str | None]:
    proc = run_cmd(
        [
            lark_bin,
            "docs",
            "+fetch",
            "--as",
            "user",
            "--doc",
            doc_id,
            "--detail",
            "with-ids",
            "--doc-format",
            "xml",
            "--scope",
            "full",
        ],
        timeout=30,
    )
    if proc.returncode != 0:
        return None, None, (proc.stderr or proc.stdout).strip()[:300]
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, None, "invalid_json_from_fetch"
    doc = (payload.get("data") or {}).get("document") or {}
    content = doc.get("content")
    revision_id = doc.get("revision_id")
    if not isinstance(content, str):
        return None, None, "missing_content_in_fetch"
    return content, revision_id, None


def _elem_text_with_breaks(elem: ET.Element) -> str:
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.tag == "br":
            parts.append("\n")
            return
        if node.tag == "cite" and node.attrib.get("type") == "user":
            uname = node.attrib.get("user-name") or node.attrib.get("user-id") or ""
            if uname:
                parts.append(uname)
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(elem)
    return "".join(parts)


def parse_member_cards_from_xml(xml_content: str) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(f"<doc>{xml_content}</doc>")
    except ET.ParseError:
        return members

    for elem in root:
        if elem.tag != "callout":
            continue
        block_id = elem.attrib.get("id", "")
        raw_text = "\n".join(_elem_text_with_breaks(p) for p in elem.findall("p"))
        if "Offer（我能兜底）" not in raw_text and "id:ou_" not in raw_text and "一句话搭伙切口" not in raw_text:
            continue

        open_id = ""
        user_name = ""
        homepage_url = ""
        homepage_doc_id = ""

        for cite in elem.iter("cite"):
            ctype = cite.attrib.get("type")
            if ctype == "user" and not open_id:
                open_id = cite.attrib.get("user-id", "")
                user_name = cite.attrib.get("user-name", "")
            elif ctype == "doc" and not homepage_doc_id:
                homepage_doc_id = cite.attrib.get("doc-id", "")

        for link in elem.iter("a"):
            href = link.attrib.get("href", "")
            if href and not homepage_url:
                homepage_url = href
                if not homepage_doc_id:
                    homepage_doc_id = extract_doc_token(href)

        if not open_id:
            m_id = re.search(r"\bid:(ou_[A-Za-z0-9_-]+)", raw_text)
            if m_id:
                open_id = m_id.group(1)

        if not homepage_doc_id:
            m_doc = re.search(r"\bdoc:([A-Za-z0-9_-]+)", raw_text)
            if m_doc:
                homepage_doc_id = m_doc.group(1)

        def grab_field(pattern: str) -> str:
            m = re.search(pattern, raw_text)
            return m.group(1).strip() if m else ""

        members.append(
            {
                "block_id": block_id,
                "open_id": open_id,
                "user_name": user_name,
                "homepage_url": homepage_url,
                "homepage_doc_id": homepage_doc_id,
                "updated_at": grab_field(r"更新[：:]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})"),
                "intro": grab_field(r"一句话搭伙切口[：:]\s*([^\n]+)"),
                "offer": grab_field(r"Offer（我能兜底）[：:]\s*([^\n]+)"),
                "seek": grab_field(r"Seek（想找同路人）[：:]\s*([^\n]+)"),
                "avoid": grab_field(r"Avoid（协作边界）[：:]\s*([^\n]+)"),
                "rhythm": grab_field(r"投入节奏与时段[：:]\s*([^\n]+)"),
                "experiment": grab_field(r"2 周微实验[：:]\s*([^\n]+)"),
                "playbooks": grab_field(r"Playbooks）[：:]\s*([^\n]+)"),
                "active_blockers": grab_field(r"Active-Blockers）[：:]\s*([^\n]+)"),
            }
        )
    return members


def init_registry_doc(
    lark_bin: str,
    title: str,
    share: str,
    confirm_share: bool,
    state_path: Path | None = None,
) -> dict[str, Any]:
    xml_body = build_index_init_xml(title)
    crt = run_cmd(
        [
            lark_bin,
            "docs",
            "+create",
            "--as",
            "user",
            "--doc-format",
            "xml",
            "--title",
            title,
            "--content",
            xml_body,
        ]
    )
    if crt.returncode != 0:
        return {
            "status": "error",
            "action": "init",
            "error": (crt.stderr or crt.stdout).strip()[:400],
        }
    payload = json.loads(crt.stdout)
    doc = ((payload.get("data") or {}).get("document")) or {}
    doc_id = doc.get("document_id")
    url = doc.get("url")
    if not doc_id:
        return {"status": "error", "action": "init", "error": "missing_document_id_in_response"}

    applied_share = "private_owner_only"
    share_warn = None
    if confirm_share and share != "none":
        applied_share, share_warn = apply_feishu_share(lark_bin, doc_id, share)

    result = {
        "status": "ok",
        "action": "created_public_index",
        "schema_version": SCHEMA_VERSION,
        "registry_doc_id": doc_id,
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
        existing["registry_doc_id"] = doc_id
        existing["registry_url"] = url
        existing["registry_share"] = applied_share
        state_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def upsert_member_to_registry(
    lark_bin: str,
    registry_doc: str,
    card_path: Path,
    homepage_url: str = "",
    homepage_doc_id: str = "",
) -> dict[str, Any]:
    reg_doc_id = extract_doc_token(registry_doc)
    if not reg_doc_id:
        return {"status": "error", "error": "missing_registry_doc_id"}
    if not card_path.is_file():
        return {"status": "error", "error": f"card_not_found:{card_path}"}

    open_id, user_name = get_feishu_identity(lark_bin)
    fields = parse_partner_card_md(card_path.read_text(encoding="utf-8"))
    updated_at = dt.date.today().isoformat()

    xml_content, _rev_id, fetch_err = fetch_doc_xml(lark_bin, reg_doc_id)
    if fetch_err or xml_content is None:
        return {"status": "error", "error": f"fetch_registry_failed:{fetch_err}"}

    members = parse_member_cards_from_xml(xml_content)
    target_block_id = ""
    for m in members:
        if open_id and m.get("open_id") == open_id:
            target_block_id = m["block_id"]
            break
        if homepage_doc_id and m.get("homepage_doc_id") == homepage_doc_id:
            target_block_id = m["block_id"]
            break

    callout_xml = build_member_callout_xml(
        fields=fields,
        open_id=open_id,
        user_name=user_name,
        homepage_url=homepage_url,
        homepage_doc_id=homepage_doc_id,
        updated_at=updated_at,
    )

    if target_block_id:
        cmd = [
            lark_bin,
            "docs",
            "+update",
            "--as",
            "user",
            "--doc",
            reg_doc_id,
            "--command",
            "block_replace",
            "--block-id",
            target_block_id,
            "--doc-format",
            "xml",
            "--content",
            callout_xml,
        ]
        action = "updated_member_block_in_place"
    else:
        cmd = [
            lark_bin,
            "docs",
            "+update",
            "--as",
            "user",
            "--doc",
            reg_doc_id,
            "--command",
            "append",
            "--doc-format",
            "xml",
            "--content",
            callout_xml,
        ]
        action = "appended_member_block"

    upd = run_cmd(cmd)
    if upd.returncode != 0:
        return {
            "status": "error",
            "action": action,
            "error": (upd.stderr or upd.stdout).strip()[:400],
        }

    # Re-fetch once to report the exact block_id after insert/replace
    post_xml, _, _ = fetch_doc_xml(lark_bin, reg_doc_id)
    final_block_id = target_block_id
    if post_xml:
        for m in parse_member_cards_from_xml(post_xml):
            if (open_id and m.get("open_id") == open_id) or (
                homepage_doc_id and m.get("homepage_doc_id") == homepage_doc_id
            ):
                final_block_id = m.get("block_id", final_block_id)
                break

    return {
        "status": "ok",
        "action": action,
        "registry_doc_id": reg_doc_id,
        "block_id": final_block_id,
        "member_open_id": open_id,
        "member_name": user_name,
        "updated_at": updated_at,
    }


def list_registry_members(lark_bin: str, registry_doc: str) -> dict[str, Any]:
    reg_doc_id = extract_doc_token(registry_doc)
    if not reg_doc_id:
        return {"status": "error", "error": "missing_registry_doc_id"}
    xml_content, rev_id, fetch_err = fetch_doc_xml(lark_bin, reg_doc_id)
    if fetch_err or xml_content is None:
        return {"status": "error", "error": f"fetch_registry_failed:{fetch_err}"}
    members = parse_member_cards_from_xml(xml_content)
    return {
        "status": "ok",
        "registry_doc_id": reg_doc_id,
        "revision_id": rev_id,
        "member_count": len(members),
        "members": members,
    }


def resolve_registry_doc(cli_arg: str, state_path: Path | None) -> str:
    if cli_arg:
        return extract_doc_token(cli_arg)
    if state_path and state_path.is_file():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("registry_doc_id"):
                return extract_doc_token(str(data["registry_doc_id"]))
        except json.JSONDecodeError:
            pass
    env_doc = os.environ.get("QT_PUBLIC_INDEX_DOC", "").strip()
    if env_doc:
        return extract_doc_token(env_doc)
    return extract_doc_token(DEFAULT_REGISTRY_DOC)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("init", "upsert", "list", "share"),
        required=True,
        help="init: create a new public index doc; upsert: register/update current member's block; list: parse all members as JSON; share: update link-sharing permission (requires --confirm-share).",
    )
    parser.add_argument(
        "--registry-doc",
        default="",
        help="Target Feishu public index doc token or URL (falls back to .card-link.json, QT_PUBLIC_INDEX_DOC, or DEFAULT_REGISTRY_DOC).",
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
        help="Path to local .card-link.json storing homepage URL/doc_id and registry_doc_id.",
    )
    parser.add_argument(
        "--title",
        default="量潮实训基地｜成员协作主页与动态检索目录（公共索引）",
        help="Title for new public index doc (for --mode init).",
    )
    parser.add_argument(
        "--share",
        choices=("none", "tenant_readable", "tenant_editable", "anyone_readable", "anyone_editable"),
        default="none",
        help="Permission level for --mode init (applied ONLY when --confirm-share is passed).",
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
        res = init_registry_doc(
            lark_bin=lark_bin,
            title=args.title,
            share=args.share,
            confirm_share=args.confirm_share,
            state_path=args.state,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["status"] == "ok" else 1

    reg_doc = resolve_registry_doc(args.registry_doc, args.state)
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
        applied, warn = apply_feishu_share(lark_bin, reg_doc, args.share)
        ok = applied == args.share
        print(
            json.dumps(
                {
                    "status": "ok" if ok else "error",
                    "registry_doc_id": reg_doc,
                    "share": applied,
                    "warning": warn,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if ok else 1

    if args.mode == "list":
        res = list_registry_members(lark_bin, reg_doc)
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
        registry_doc=reg_doc,
        card_path=args.card,
        homepage_url=homepage_url,
        homepage_doc_id=homepage_doc_id,
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
        existing["registry_doc_id"] = res["registry_doc_id"]
        existing["registry_block_id"] = res.get("block_id", "")
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
