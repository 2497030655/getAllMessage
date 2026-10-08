# -*- coding: utf-8 -*-
"""记录管道：抓包 → 解析 IM → 入库。"""
from __future__ import annotations

import base64
import json
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.config import AGENT_MODE, DEFAULT_CONV_ID, PLATFORM_XHS
from app.platforms.xhs.payload import (
    find_xhs_im_json_objects,
    parse_xhs_im_message_obj,
    xhs_msg_to_event,
)
from app.utils.protobuf import (
    extract_send_text_from_protobuf,
    parse_protobuf_hex_ids,
    try_b64_decode_ws,
)
from app.utils.text import (
    is_garbled_text,
    is_media_placeholder,
    is_valid_chat_content,
    is_valid_display_name,
)
from app.utils.timefmt import try_format_json
from app.config import IM_PROTO_TEMPLATE_B64 as _DEFAULT_TPL
from app.config import IM_TEMPLATE_TEXT as _DEFAULT_TXT

if TYPE_CHECKING:
    from app.context import AppContext


class RecordPipeline:
    def __init__(self, app: "AppContext") -> None:
        self.app = app
        self.im_proto_template_b64 = _DEFAULT_TPL
        self.im_template_text = _DEFAULT_TXT


    def extract_im_events(self, rec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从一条 WS 记录解析全部 IM 聊天事件（支持批量推送）。"""
        if rec.get('kind') != 'WebSocket':
            return []
        method = rec.get('method', '')
        url = rec.get('url', '')
        time = rec.get('time', '')
        account_id = str(rec.get('account_id') or '')
        my_uid = self.app.accounts.xhs_uid(account_id)
        body_up = str(rec.get('requestBody') or '')
        body_down = str(rec.get('responseBody') or '')
        if method == 'WS↑' and 'sendMessage' in body_up:
            ev = self._extract_send_message_event(body_up, url, time, account_id, my_uid)
            return [ev] if ev else []
        if method != 'WS↓':
            return []
        events = self.app.xhs_parser.extract_ws_down_events(
            body_down, url, time, account_id=account_id, my_uid=my_uid
        )
        if 'frontier-im' in url or 'douyin.com' in url:
            events.extend(
                self.app.douyin_parser.extract_douyin_im_events(
                    body_down, url, time, account_id=account_id
                )
            )
        for ev in events:
            ev.setdefault('account_id', account_id)
        return events

    def _extract_send_message_event(
        self,
        body_up: str,
        url: str,
        time: str,
        account_id: str = "",
        my_uid: str = "",
    ) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(body_up)
            inner_b64 = data.get('b', {}).get('d', {}).get('b')
            if not inner_b64 or not isinstance(inner_b64, str):
                return None
            raw = base64.b64decode(inner_b64)
            text = extract_send_text_from_protobuf(raw)
            if not text or is_garbled_text(text):
                return None
            hex_ids = parse_protobuf_hex_ids(raw)
            me = str(my_uid or "").strip()
            # 存的 uid 若根本不在本包里，多半是别的账号的，不能拿来当“我”
            if me and me not in hex_ids:
                me = ""
            if me:
                conv_id = next((h for h in hex_ids if h != me), "") or DEFAULT_CONV_ID
            elif len(hex_ids) >= 2:
                conv_id = hex_ids[1]
            elif hex_ids:
                conv_id = hex_ids[0]
            else:
                conv_id = DEFAULT_CONV_ID
            return {
                'direction': 'up',
                'text': text,
                'conv_id': conv_id,
                'template_b64': inner_b64,
                'template_text': text,
                'url': url,
                'time': time,
                'platform': PLATFORM_XHS,
                'account_id': account_id,
            }
        except Exception:
            return None

    def extract_im_event(self, rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        events = self.extract_im_events(rec)
        return events[0] if events else None

    def emit_record(self, entry: Dict[str, Any]) -> None:
        """抓包入口：Agent 模式上报云端；否则本地解析 + UI。"""
        try:
            self.update_send_template_from_record(entry)
            if AGENT_MODE:
                # 仍上报原始包（兼容旧云端），同时上报本地解析结果（避免 front_chain 昵称当正文）
                self.app.cloud_agent.upload_record(entry)
                self._upload_parsed_events(entry)
                return
            enriched = self.enrich_chat_record(entry)
            if enriched.get('method') == 'WS↓':
                ws_url = str(enriched.get('url', ''))
                body = str(enriched.get('responseBody') or '')
                if 'frontier-im' in ws_url or 'douyin.com' in ws_url:
                    meta = self.app.douyin_parser.parse_douyin_ws_meta(body)
                    if meta:
                        enriched['douyinMeta'] = meta
                        cid = str(meta.get('conversation_id', ''))
                        if cid:
                            self.app.douyin_parser.ensure_douyin_contact(
                                cid, ws_url, str(enriched.get("account_id") or "")
                            )
                        cmd = meta.get('command_type')
                        if cmd == 14:
                            enriched['chatPreview'] = f"抖音·未读同步({meta.get('read_badge_count', '')})"
            events = self.extract_im_events(enriched)
            if not events and enriched.get('kind') == 'WebSocket':
                ws_url = str(enriched.get('url', ''))
                body = str(enriched.get('responseBody') or enriched.get('requestBody') or '')
                if 'frontier-im' not in ws_url and 'douyin.com' not in ws_url:
                    for chat in self.extract_chat_from_ws(enriched):
                        ev = self.app.xhs_parser._event_from_chat_dict(
                            chat,
                            ws_url,
                            str(enriched.get("time", "")),
                            body,
                            account_id=str(enriched.get("account_id") or ""),
                            my_uid=self.app.accounts.xhs_uid(
                                str(enriched.get("account_id") or "")
                            ),
                        )
                        if ev:
                            events.append(ev)
            for ev in events:
                if ev.get('text') or ev.get('image_url'):
                    if ev.get('image_url') and not ev.get('text'):
                        ev['text'] = '[图片]'
                    ws_url = str(enriched.get('url', ''))
                    conv_id = self.app.contacts.upsert_from_event(ev, ws_url)
                    enriched['conv_id'] = conv_id
                    enriched['chatPreview'] = ev.get('text') or ''
                    c = self.app.contacts.get(conv_id)
                    if c and c.get('platform') == PLATFORM_XHS:
                        if not is_valid_display_name(c.get('nickname', '')):
                            self.app.dom_sync.schedule_scrape_chat_username(conv_id)
                    if ev.get('direction') == 'down':
                        aid = str(ev.get("account_id") or enriched.get("account_id") or "")
                        if aid == self.app.accounts.active_id and not self.app.contacts.get_active():
                            self.app.contacts.set_active(conv_id)
                    self.app.bridge.post_contact(conv_id)
            self.app.bridge.post_record(enriched)
        except Exception:
            try:
                self.app.bridge.post_record(entry)
            except Exception:
                pass

    def _upload_parsed_events(self, entry: Dict[str, Any]) -> None:
        """Agent 模式：本地解析后把干净事件交给云端入库/推送。"""
        try:
            enriched = self.enrich_chat_record(dict(entry))
            account_id = str(enriched.get("account_id") or "default")
            events = self.extract_im_events(enriched)
            if not events and enriched.get("kind") == "WebSocket":
                ws_url = str(enriched.get("url", ""))
                body = str(
                    enriched.get("responseBody") or enriched.get("requestBody") or ""
                )
                if "frontier-im" not in ws_url and "douyin.com" not in ws_url:
                    for chat in self.extract_chat_from_ws(enriched):
                        ev = self.app.xhs_parser._event_from_chat_dict(
                            chat,
                            ws_url,
                            str(enriched.get("time", "")),
                            body,
                            account_id=account_id,
                            my_uid=self.app.accounts.xhs_uid(account_id),
                        )
                        if ev:
                            events.append(ev)
            payload = []
            for ev in events:
                text = str(ev.get("text") or "").strip()
                nick = str(ev.get("nickname") or "").strip()
                if ev.get("image_url") and not text:
                    text = "[图片]"
                if not text or (nick and text == nick):
                    continue
                ws_url = str(enriched.get("url", ""))
                conv_key = self.app.contacts.upsert_from_event(ev, ws_url)
                contact = self.app.contacts.get(conv_key) or {}
                payload.append(
                    {
                        "conv_key": conv_key,
                        "conv_id": contact.get("conv_id") or ev.get("conv_id"),
                        "account_id": account_id,
                        "platform": contact.get("platform") or ev.get("platform") or PLATFORM_XHS,
                        "nickname": contact.get("nickname") or nick,
                        "direction": ev.get("direction") or "down",
                        "text": text,
                        "time": ev.get("time") or enriched.get("time") or "",
                    }
                )
            if payload:
                self.app.cloud_agent.upload_im_events(payload)
        except Exception:
            pass

    def update_send_template_from_record(self, rec: Dict[str, Any]) -> None:
        """用最近一条真实 sendMessage 更新发送模板。"""
        if rec.get('method') != 'WS↑':
            return
        body = str(rec.get('requestBody') or '')
        if 'sendMessage' not in body:
            return
        try:
            data = json.loads(body)
            inner = data.get('b', {}).get('d', {}).get('b')
            if not inner:
                return
            raw = base64.b64decode(inner)
            self.im_proto_template_b64 = inner
            for old in (self.im_template_text, '你好', 'hello还在吗'):
                if old.encode('utf-8') in raw:
                    idx = raw.find(old.encode('utf-8'))
                    if idx > 0 and raw[idx - 1] == len(old.encode('utf-8')):
                        self.im_template_text = old
                        break
        except Exception:
            pass

    def is_im_related(self, rec: Dict[str, Any]) -> bool:
        if rec.get('chatMessages') or rec.get('chatPreview'):
            return True
        parts = [str(rec.get('url', '')), str(rec.get('requestBody', '')), str(rec.get('responseBody', ''))]
        blob = ' '.join(parts).lower()
        return '"bizname":"im"' in blob.replace(' ', '') or 'bizname":"im' in blob or '/im/' in blob or ('/im?' in blob)

    def extract_chat_from_ws(self, rec: Dict[str, Any]) -> List[Dict[str, Any]]:
        body = str(rec.get('responseBody') or rec.get('requestBody') or '')
        if not body:
            return []
        messages: List[Dict[str, Any]] = []
        seen: set = set()
    
        def add(msg: Dict[str, Any]) -> None:
            content = msg.get('content', '')
            if not content or content in seen:
                return
            seen.add(content)
            messages.append(msg)
        for m in re.finditer('\\\\"content\\\\":\\\\"([^\\\\"]+)\\\\"', body):
            add({'content': m.group(1), 'nickname': '', 'source': 'push'})
        nick_m = re.search('\\\\"nickname\\\\":\\\\"([^\\\\"]*)\\\\"', body)
        nickname = nick_m.group(1) if nick_m else ''
        # front_chain 常是预览/昵称，不能无条件当正文；仅在没有 content 时作兜底
        if not messages:
            for m in re.finditer('\\\\"front_chain\\\\":\\\\"([^\\\\"]+)\\\\"', body):
                fc = m.group(1).strip()
                if not fc or fc == nickname:
                    continue
                if not is_valid_chat_content(fc) or is_media_placeholder(fc):
                    continue
                add({'content': fc, 'nickname': nickname, 'source': 'front_chain'})
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = None
    
        def walk(obj: Any, depth: int=0) -> None:
            if depth > 12:
                return
            if isinstance(obj, dict):
                parsed = parse_xhs_im_message_obj(obj)
                if parsed:
                    content = str(parsed.get('content') or '').strip()
                    nick = str(parsed.get('nickname') or nickname or '').strip()
                    # 正文等于昵称 → 解析串了，丢弃
                    if content and content != nick:
                        add({
                            'content': content,
                            'nickname': nick,
                            'sender': parsed.get('sender', ''),
                            'receiver': parsed.get('receiver', ''),
                            'source': 'json',
                        })
                content = obj.get('content')
                if isinstance(content, str) and content:
                    if content.startswith('{') and content.endswith('}'):
                        try:
                            inner = json.loads(content.replace('\\"', '"'))
                            walk(inner, depth + 1)
                        except json.JSONDecodeError:
                            pass
                for v in obj.values():
                    walk(v, depth + 1)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v, depth + 1)
            elif isinstance(obj, str) and len(obj) > 20:
                if re.fullmatch('[A-Za-z0-9+/=]+', obj) and len(obj) > 24:
                    try:
                        raw = base64.b64decode(obj, validate=False)
                        parsed = self.app.xhs_parser.parse_im_push_payload(obj)
                        if parsed and parsed.get('content'):
                            content = str(parsed.get('content') or '').strip()
                            nick = str(parsed.get('nickname') or nickname or '').strip()
                            if content and content != nick:
                                add({
                                    'content': content,
                                    'nickname': nick,
                                    'sender': parsed.get('sender', ''),
                                    'receiver': parsed.get('receiver', ''),
                                    'source': 'push_b64',
                                })
                        else:
                            text = raw.decode('utf-8', errors='ignore')
                            for pat in ('\\\\"content\\\\":\\\\"([^\\\\"]+)\\\\"', '"content":"([^"]+)"'):
                                for m in re.finditer(pat, text):
                                    c = m.group(1).strip()
                                    if c and c != nickname:
                                        add({'content': c, 'nickname': nickname, 'source': 'protobuf'})
                    except Exception:
                        pass
        if data is not None:
            walk(data)
        # 去掉「正文=昵称」的脏数据
        cleaned = []
        for msg in messages:
            c = str(msg.get('content') or '').strip()
            n = str(msg.get('nickname') or nickname or '').strip()
            if not c or (n and c == n):
                continue
            if not msg.get('nickname') and nickname:
                msg = dict(msg)
                msg['nickname'] = nickname
            cleaned.append(msg)
        return cleaned

    def enrich_chat_record(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        if rec.get('kind') != 'WebSocket':
            return rec
        ev = self.extract_im_event(rec)
        if ev and ev.get('text'):
            rec['chatMessages'] = [{'content': ev['text'], 'nickname': ev.get('nickname', ''), 'sender': ev.get('conv_id', '')}]
            rec['chatPreview'] = ev['text']
            if ev.get('conv_id'):
                rec['conv_id'] = ev['conv_id']
            return rec
        chats = self.extract_chat_from_ws(rec)
        if chats:
            rec['chatMessages'] = chats
            rec['chatPreview'] = chats[0].get('content', '')
        return rec

    def parse_ws_chat_event(self, rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """从 WS↑ / WS↓ 解析可展示的聊天事件。"""
        events = self.parse_ws_chat_events(rec)
        return events[0] if events else None

    def parse_ws_chat_events(self, rec: Dict[str, Any]) -> List[Dict[str, Any]]:
        events = self.extract_im_events(rec)
        result: List[Dict[str, Any]] = []
        for ev in events:
            if not ev.get('text'):
                continue
            labeled = dict(ev)
            labeled['label'] = 'WS↑ 发送' if ev['direction'] == 'up' else 'WS↓ 接收'
            result.append(labeled)
        return result

    def format_record_detail(self, rec: Dict[str, Any]) -> str:
        display: Dict[str, Any] = dict(rec)
        for field in ('requestBody', 'responseBody'):
            raw = display.get(field)
            if raw:
                display[field] = try_format_json(str(raw))
        chats = rec.get('chatMessages') or self.extract_chat_from_ws(rec)
        lines: List[str] = []
        if rec.get('douyinMeta'):
            lines.append('════ 抖音 IM 解码 ════')
            lines.append(json.dumps(rec['douyinMeta'], ensure_ascii=False, indent=2))
            if rec['douyinMeta'].get('command_type') == 14:
                lines.append('说明: command_type=14 为会话未读数同步，不含聊天正文；对方发文字时会出现带 text/content 的包。')
            lines.append('')
        elif rec.get('kind') == 'WebSocket':
            body = str(rec.get('responseBody') or rec.get('requestBody') or '')
            meta = self.app.douyin_parser.parse_douyin_ws_meta(body)
            if meta:
                lines.append('════ 抖音 IM 解码 ════')
                lines.append(json.dumps(meta, ensure_ascii=False, indent=2))
                if meta.get('command_type') == 14:
                    lines.append('说明: command_type=14 为会话未读数同步，不含聊天正文。')
                lines.append('')
        if chats:
            lines.append('════ 聊天内容（推送解析）════')
            for (i, c) in enumerate(chats, 1):
                lines.append(f"  [{i}] 内容: {c.get('content', '')}" + (f"  昵称: {c.get('nickname')}" if c.get('nickname') else ''))
            lines.append('')
        try:
            body = rec.get('requestBody') or ''
            if isinstance(body, str) and 'sendMessage' in body:
                outer = json.loads(body) if body.strip().startswith('{') else None
                if outer is None and rec.get('method') == 'WS↑':
                    outer = json.loads(try_format_json(body).replace('\n', ''))
                inner_b64 = outer.get('b', {}).get('d', {}).get('b') if isinstance(outer, dict) else None
                if inner_b64:
                    pb = base64.b64decode(inner_b64)
                    display['_decodedTextHint'] = pb.decode('utf-8', errors='ignore')
        except Exception:
            pass
        if self.is_im_related(rec):
            lines.append('════ IM 聊天相关 ════')
        lines.append(json.dumps(display, ensure_ascii=False, indent=2))
        return '\n'.join(lines)
