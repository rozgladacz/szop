(function initRefreshPriorityModule(globalScope) {
  function normalizeRosterRefreshCycleToken(cycleToken, fallbackVersion = 0) {
    const fallback = Number.isFinite(Number(fallbackVersion)) ? Number(fallbackVersion) : 0;
    if (!cycleToken || typeof cycleToken !== 'object') {
      return {
        dedupeKey: cycleToken ? String(cycleToken) : null,
        version: fallback,
        authoritative: false,
      };
    }
    const rawVersion = Number(cycleToken.version);
    const normalizedVersion = Number.isFinite(rawVersion) ? rawVersion : fallback;
    const dedupeKeyValue = cycleToken.dedupeKey ?? cycleToken.key ?? cycleToken.token ?? null;
    return {
      dedupeKey: dedupeKeyValue ? String(dedupeKeyValue) : null,
      version: normalizedVersion,
      authoritative: cycleToken.authoritative === true,
    };
  }

  function resolveRosterRefreshPriority(state, cycleToken) {
    const currentState = state && typeof state === 'object'
      ? state
      : { latestAppliedVersion: 0, latestAuthoritativeVersion: 0 };
    const token = normalizeRosterRefreshCycleToken(cycleToken, currentState.latestAppliedVersion || 0);
    const nextState = {
      latestAppliedVersion: Number.isFinite(Number(currentState.latestAppliedVersion))
        ? Number(currentState.latestAppliedVersion)
        : 0,
      latestAuthoritativeVersion: Number.isFinite(Number(currentState.latestAuthoritativeVersion))
        ? Number(currentState.latestAuthoritativeVersion)
        : 0,
    };
    const version = Number.isFinite(token.version) ? token.version : 0;
    if (version < nextState.latestAppliedVersion) {
      return { apply: false, token, state: nextState };
    }
    if (!token.authoritative && version < nextState.latestAuthoritativeVersion) {
      return { apply: false, token, state: nextState };
    }
    nextState.latestAppliedVersion = Math.max(nextState.latestAppliedVersion, version);
    if (token.authoritative) {
      nextState.latestAuthoritativeVersion = Math.max(nextState.latestAuthoritativeVersion, version);
    }
    return { apply: true, token, state: nextState };
  }

  globalScope.SZOPRefreshPriority = {
    normalizeRosterRefreshCycleToken,
    resolveRosterRefreshPriority,
  };
}(window));
