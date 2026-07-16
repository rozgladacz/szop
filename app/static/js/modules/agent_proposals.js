(function initSZOPAgentProposalsModule(globalScope) {
  const STATUS_META = {
    pending: { label: 'Oczekuje', badgeClass: 'text-bg-warning' },
    approved: { label: 'Zezwolono', badgeClass: 'text-bg-success' },
    executed: { label: 'Wykonano', badgeClass: 'text-bg-success' },
    rejected: { label: 'Odrzucono', badgeClass: 'text-bg-secondary' },
    stale: { label: 'Nieaktualna', badgeClass: 'text-bg-danger' },
  };

  function normalizeAgentProposals(proposals) {
    return Array.isArray(proposals) ? proposals.filter(Boolean) : [];
  }

  function agentProposalStatusMeta(status) {
    return STATUS_META[status] || { label: status || 'Nieznany', badgeClass: 'text-bg-light' };
  }

  function countPendingAgentProposals(proposals) {
    return normalizeAgentProposals(proposals).filter((proposal) => proposal.status === 'pending').length;
  }

  function agentProposalDecisionUrl(proposalId, decision) {
    if (decision !== 'approve' && decision !== 'reject') {
      throw new Error(`Unsupported agent proposal decision: ${decision}`);
    }
    return `/agent_proposals/${encodeURIComponent(String(proposalId))}/${decision}`;
  }

  function formatAgentProposalTimestamp(value) {
    if (!value) {
      return '';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }
    return date.toLocaleString('pl-PL');
  }

  function agentProposalPayloadText(payload) {
    try {
      return JSON.stringify(payload || {}, null, 2);
    } catch (err) {
      return '{}';
    }
  }

  function agentProposalResultText(proposal) {
    const result = proposal && proposal.result;
    if (!result || typeof result !== 'object') {
      return '';
    }
    if (proposal.status === 'executed') {
      return [
        `Akcja wykonana w bitwie #${result.battle_id}.`,
        `Sekwencja: ${result.previous_sequence} → ${result.new_sequence}.`,
        `Zapisane zdarzenia: ${result.event_count}.`,
      ].join(' ');
    }
    if (proposal.status === 'stale') {
      return [
        `Akcja nie została wykonana w bitwie #${result.battle_id}.`,
        `Oczekiwana sekwencja ${result.expected_sequence},`,
        `aktualna ${result.actual_sequence}.`,
      ].join(' ');
    }
    return '';
  }

  function replaceAgentProposal(proposals, updatedProposal) {
    const current = normalizeAgentProposals(proposals);
    let replaced = false;
    const next = current.map((proposal) => {
      if (String(proposal.id) === String(updatedProposal.id)) {
        replaced = true;
        return updatedProposal;
      }
      return proposal;
    });
    if (!replaced) {
      next.unshift(updatedProposal);
    }
    return next;
  }

  function setPanelMessage(panel, message, kind) {
    const alertEl = panel.querySelector('[data-agent-proposals-alert]');
    if (!alertEl) {
      return;
    }
    if (!message) {
      alertEl.className = 'alert alert-danger py-2 mb-3 d-none';
      alertEl.textContent = '';
      return;
    }
    alertEl.className = `alert alert-${kind || 'danger'} py-2 mb-3`;
    alertEl.textContent = message;
  }

  function updateProposalCount(panel, proposals) {
    const countEl = panel.querySelector('[data-agent-proposals-count]');
    if (!countEl) {
      return;
    }
    const pending = countPendingAgentProposals(proposals);
    countEl.className = `badge rounded-pill ${pending ? 'text-bg-warning' : 'text-bg-secondary'}`;
    countEl.textContent = pending ? `${pending} oczekuje` : 'Brak oczekujących';
  }

  function appendText(parent, tagName, className, text) {
    const element = parent.ownerDocument.createElement(tagName);
    if (className) {
      element.className = className;
    }
    element.textContent = text;
    parent.appendChild(element);
    return element;
  }

  function renderAgentProposalCard(documentRef, proposal) {
    const item = documentRef.createElement('article');
    item.className = 'list-group-item py-3';
    item.setAttribute('data-agent-proposal-id', String(proposal.id));

    const header = documentRef.createElement('div');
    header.className = 'd-flex flex-column flex-lg-row justify-content-between gap-2';
    item.appendChild(header);

    const titleBox = documentRef.createElement('div');
    titleBox.className = 'flex-grow-1';
    header.appendChild(titleBox);

    appendText(titleBox, 'h3', 'h6 mb-1', proposal.summary || 'Bez opisu');
    appendText(titleBox, 'code', 'small', proposal.action || 'unknown');

    const metaBox = documentRef.createElement('div');
    metaBox.className = 'd-flex flex-row flex-lg-column align-items-start align-items-lg-end gap-2';
    header.appendChild(metaBox);

    const statusMeta = agentProposalStatusMeta(proposal.status);
    appendText(metaBox, 'span', `badge ${statusMeta.badgeClass}`, statusMeta.label);

    const createdAt = formatAgentProposalTimestamp(proposal.created_at);
    if (createdAt) {
      appendText(metaBox, 'span', 'small text-muted', `Utworzono: ${createdAt}`);
    }

    if (proposal.decided_at) {
      appendText(
        metaBox,
        'span',
        'small text-muted',
        `Decyzja: ${formatAgentProposalTimestamp(proposal.decided_at)}`,
      );
    }

    const resultText = agentProposalResultText(proposal);
    if (resultText) {
      appendText(item, 'p', 'alert alert-light border py-2 px-3 mt-3 mb-0 small', resultText);
    }

    const details = documentRef.createElement('details');
    details.className = 'mt-3';
    item.appendChild(details);
    appendText(details, 'summary', 'small text-muted', 'Payload');
    const pre = appendText(
      details,
      'pre',
      'bg-light border rounded small p-2 mt-2 mb-0 overflow-auto',
      agentProposalPayloadText(proposal.payload),
    );
    pre.style.maxHeight = '12rem';

    if (proposal.status === 'pending') {
      const actions = documentRef.createElement('div');
      actions.className = 'd-flex justify-content-end gap-2 mt-3';
      item.appendChild(actions);

      const approveLabel = proposal.action === 'battle:action'
        ? 'Zezwól i wykonaj'
        : 'Zezwól';
      const approveButton = appendText(
        actions,
        'button',
        'btn btn-sm btn-success',
        approveLabel,
      );
      approveButton.type = 'button';
      approveButton.setAttribute('data-agent-proposal-action', 'approve');

      const rejectButton = appendText(actions, 'button', 'btn btn-sm btn-outline-danger', 'Odrzuć');
      rejectButton.type = 'button';
      rejectButton.setAttribute('data-agent-proposal-action', 'reject');
    }

    return item;
  }

  function renderAgentProposals(panel, proposals) {
    const listEl = panel.querySelector('[data-agent-proposals-list]');
    const normalized = normalizeAgentProposals(proposals);
    panel.__szopAgentProposals = normalized;
    updateProposalCount(panel, normalized);
    if (!listEl) {
      return;
    }
    listEl.innerHTML = '';
    if (normalized.length === 0) {
      appendText(listEl, 'div', 'list-group-item text-muted', 'Brak propozycji agentów.');
      return;
    }
    normalized.forEach((proposal) => {
      listEl.appendChild(renderAgentProposalCard(listEl.ownerDocument, proposal));
    });
  }

  function setCardPending(card, pending) {
    card.querySelectorAll('[data-agent-proposal-action]').forEach((button) => {
      button.disabled = pending;
    });
  }

  function ensureJsonResponse(response) {
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  }

  function loadAgentProposals(panel) {
    const endpoint = panel.dataset.proposalsEndpoint || '/agent_proposals';
    setPanelMessage(panel, '', 'danger');
    return fetch(endpoint, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    })
      .then(ensureJsonResponse)
      .then((proposals) => {
        renderAgentProposals(panel, proposals);
        return proposals;
      })
      .catch((err) => {
        setPanelMessage(panel, 'Nie udało się pobrać propozycji agentów.', 'danger');
        throw err;
      });
  }

  function decideAgentProposal(panel, proposalId, decision) {
    setPanelMessage(panel, '', 'danger');
    return fetch(agentProposalDecisionUrl(proposalId, decision), {
      method: 'POST',
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    })
      .then(ensureJsonResponse)
      .then((updatedProposal) => {
        const next = replaceAgentProposal(panel.__szopAgentProposals || [], updatedProposal);
        renderAgentProposals(panel, next);
        if (updatedProposal.status === 'executed') {
          setPanelMessage(panel, 'Akcja została wykonana.', 'success');
        } else if (updatedProposal.status === 'stale') {
          setPanelMessage(panel, 'Akcja nie została wykonana, bo stan bitwy się zmienił.', 'warning');
        } else {
          setPanelMessage(panel, 'Decyzja zapisana.', 'success');
        }
        return updatedProposal;
      })
      .catch((err) => {
        setPanelMessage(panel, 'Nie udało się zapisać decyzji.', 'danger');
        throw err;
      });
  }

  function initAgentProposals(root) {
    const scope = root || globalScope.document;
    if (!scope || !scope.querySelectorAll) {
      return;
    }
    scope.querySelectorAll('[data-agent-proposals-panel]').forEach((panel) => {
      if (panel.dataset.agentProposalsInitialized === '1') {
        return;
      }
      panel.dataset.agentProposalsInitialized = '1';
      const listEl = panel.querySelector('[data-agent-proposals-list]');
      if (listEl) {
        listEl.addEventListener('click', (event) => {
          const target = event.target;
          const button = target && target.closest
            ? target.closest('[data-agent-proposal-action]')
            : null;
          if (!button || !listEl.contains(button)) {
            return;
          }
          const card = button.closest('[data-agent-proposal-id]');
          if (!card) {
            return;
          }
          const decision = button.getAttribute('data-agent-proposal-action');
          const proposalId = card.getAttribute('data-agent-proposal-id');
          setCardPending(card, true);
          decideAgentProposal(panel, proposalId, decision).catch(() => {
            setCardPending(card, false);
          });
        });
      }
      loadAgentProposals(panel).catch(() => {});
    });
  }

  const api = {
    agentProposalDecisionUrl,
    agentProposalPayloadText,
    agentProposalResultText,
    agentProposalStatusMeta,
    countPendingAgentProposals,
    decideAgentProposal,
    formatAgentProposalTimestamp,
    initAgentProposals,
    loadAgentProposals,
    normalizeAgentProposals,
    renderAgentProposals,
    replaceAgentProposal,
  };

  globalScope.SZOPAgentProposals = api;
  globalScope.initAgentProposals = initAgentProposals;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPAgentProposals = api;
    globalThis.initAgentProposals = initAgentProposals;
  }

  const documentRef = globalScope.document;
  if (documentRef && documentRef.addEventListener) {
    if (documentRef.readyState === 'loading') {
      documentRef.addEventListener('DOMContentLoaded', () => initAgentProposals(documentRef));
    } else {
      initAgentProposals(documentRef);
    }
  }
}(typeof window !== 'undefined' ? window : globalThis));
