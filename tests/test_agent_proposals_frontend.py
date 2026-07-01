from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

from tests.node_runtime import resolve_node_binary


ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT_DIR / "app/static/js/modules/agent_proposals.js"
BASE_TEMPLATE_PATH = ROOT_DIR / "app/templates/base.html"
INDEX_TEMPLATE_PATH = ROOT_DIR / "app/templates/index.html"


def _run_node(script: str) -> dict[str, object]:
    completed = subprocess.run(
        [resolve_node_binary(), "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = completed.stdout.strip()
    assert stdout, "Node script produced no output"
    return json.loads(stdout)


def test_agent_proposals_template_mounts_panel_and_script() -> None:
    base_template = BASE_TEMPLATE_PATH.read_text(encoding="utf-8")
    index_template = INDEX_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "/js/modules/agent_proposals.js" in base_template
    assert "data-agent-proposals-panel" in index_template
    assert 'data-proposals-endpoint="/agent_proposals"' in index_template
    assert "data-agent-proposals-list" in index_template
    assert "data-agent-proposals-count" in index_template


def test_agent_proposals_module_exports_pure_helpers() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({json.dumps(str(MODULE_PATH))}, 'utf8');
        const registeredEvents = [];
        const documentStub = {{
          readyState: 'loading',
          addEventListener: (eventName) => registeredEvents.push(eventName),
          querySelectorAll: () => [],
        }};
        const sandbox = {{
          console,
          JSON,
          Date,
          Number,
          String,
          Array,
          Object,
          Error,
          encodeURIComponent,
          window: {{ document: documentStub }},
        }};
        sandbox.window.window = sandbox.window;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox, {{ filename: {json.dumps(str(MODULE_PATH))} }});
        const api = sandbox.window.SZOPAgentProposals;
        let invalidDecisionRejected = false;
        try {{
          api.agentProposalDecisionUrl(1, 'archive');
        }} catch (err) {{
          invalidDecisionRejected = true;
        }}
        const next = api.replaceAgentProposal(
          [
            {{ id: 1, status: 'pending', summary: 'Stara' }},
            {{ id: 2, status: 'approved', summary: 'Gotowa' }},
            null,
          ],
          {{ id: 1, status: 'rejected', summary: 'Nowa' }},
        );
        console.log(JSON.stringify({{
          pendingCount: api.countPendingAgentProposals([
            {{ id: 1, status: 'pending' }},
            {{ id: 2, status: 'approved' }},
            null,
          ]),
          approveUrl: api.agentProposalDecisionUrl('abc/1', 'approve'),
          rejectedLabel: api.agentProposalStatusMeta('rejected').label,
          unknownLabel: api.agentProposalStatusMeta('').label,
          invalidDecisionRejected,
          invalidTimestamp: api.formatAgentProposalTimestamp('not-a-date'),
          payloadText: api.agentProposalPayloadText({{ nested: {{ value: '<safe>' }} }}),
          nextIds: next.map((proposal) => proposal.id),
          nextStatuses: next.map((proposal) => proposal.status),
          registeredEvents,
        }}));
        """
    )

    result = _run_node(script)

    assert result["pendingCount"] == 1
    assert result["approveUrl"] == "/agent_proposals/abc%2F1/approve"
    assert result["rejectedLabel"] == "Odrzucono"
    assert result["unknownLabel"] == "Nieznany"
    assert result["invalidDecisionRejected"] is True
    assert result["invalidTimestamp"] == "not-a-date"
    assert '"<safe>"' in result["payloadText"]
    assert result["nextIds"] == [1, 2]
    assert result["nextStatuses"] == ["rejected", "approved"]
    assert result["registeredEvents"] == ["DOMContentLoaded"]


def test_agent_proposals_module_renders_empty_and_pending_states() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({json.dumps(str(MODULE_PATH))}, 'utf8');

        class FakeElement {{
          constructor(tagName, ownerDocument) {{
            this.tagName = tagName;
            this.ownerDocument = ownerDocument;
            this.children = [];
            this.attributes = {{}};
            this.style = {{}};
            this.textContent = '';
            this.className = '';
          }}

          appendChild(child) {{
            this.children.push(child);
            child.parentElement = this;
            return child;
          }}

          setAttribute(name, value) {{
            this.attributes[name] = String(value);
          }}

          getAttribute(name) {{
            return this.attributes[name] || null;
          }}

          set innerHTML(value) {{
            this.children = [];
            this._innerHTML = String(value);
          }}

          get innerHTML() {{
            return this._innerHTML || '';
          }}

          querySelector(selector) {{
            return collect(this).find((node) => matches(node, selector)) || null;
          }}

          querySelectorAll(selector) {{
            return collect(this).filter((node) => matches(node, selector));
          }}
        }}

        function collect(node) {{
          const result = [];
          for (const child of node.children || []) {{
            result.push(child, ...collect(child));
          }}
          return result;
        }}

        function matches(node, selector) {{
          const attrMatch = selector.match(/^\\[([^\\]]+)\\]$/);
          return Boolean(attrMatch && Object.prototype.hasOwnProperty.call(node.attributes, attrMatch[1]));
        }}

        const registeredEvents = [];
        const documentStub = {{
          readyState: 'loading',
          addEventListener: (eventName) => registeredEvents.push(eventName),
          querySelectorAll: () => [],
          createElement: (tagName) => new FakeElement(tagName, documentStub),
        }};
        const sandbox = {{
          console,
          JSON,
          Date,
          Number,
          String,
          Array,
          Object,
          Error,
          encodeURIComponent,
          window: {{ document: documentStub }},
        }};
        sandbox.window.window = sandbox.window;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox, {{ filename: {json.dumps(str(MODULE_PATH))} }});
        const api = sandbox.window.SZOPAgentProposals;

        const panel = new FakeElement('section', documentStub);
        const count = new FakeElement('span', documentStub);
        count.setAttribute('data-agent-proposals-count', '');
        const alert = new FakeElement('div', documentStub);
        alert.setAttribute('data-agent-proposals-alert', '');
        const list = new FakeElement('div', documentStub);
        list.setAttribute('data-agent-proposals-list', '');
        panel.appendChild(count);
        panel.appendChild(alert);
        panel.appendChild(list);

        api.renderAgentProposals(panel, []);
        const emptyText = list.children[0].textContent;
        const emptyCount = count.textContent;

        api.renderAgentProposals(panel, [
          {{
            id: 10,
            action: 'rosters.update',
            summary: 'Zmień rozpiskę',
            status: 'pending',
            payload: {{ roster_id: 3 }},
            created_at: '2026-07-01T10:00:00Z',
          }},
          {{
            id: 11,
            action: 'armies.inspect',
            summary: 'Sprawdź armię',
            status: 'approved',
            payload: {{}},
            created_at: '2026-07-01T09:00:00Z',
            decided_at: '2026-07-01T09:30:00Z',
          }},
        ]);
        const buttons = collect(list).filter((node) => node.attributes['data-agent-proposal-action']);
        const payloadPre = collect(list).find((node) => node.tagName === 'pre');

        console.log(JSON.stringify({{
          emptyText,
          emptyCount,
          renderedItems: list.children.length,
          pendingCountLabel: count.textContent,
          buttonActions: buttons.map((button) => button.attributes['data-agent-proposal-action']),
          firstTitle: collect(list.children[0]).find((node) => node.tagName === 'h3').textContent,
          payloadText: payloadPre.textContent,
          registeredEvents,
        }}));
        """
    )

    result = _run_node(script)

    assert result["emptyText"] == "Brak propozycji agentów."
    assert result["emptyCount"] == "Brak oczekujących"
    assert result["renderedItems"] == 2
    assert result["pendingCountLabel"] == "1 oczekuje"
    assert result["buttonActions"] == ["approve", "reject"]
    assert result["firstTitle"] == "Zmień rozpiskę"
    assert '"roster_id": 3' in result["payloadText"]
    assert result["registeredEvents"] == ["DOMContentLoaded"]
