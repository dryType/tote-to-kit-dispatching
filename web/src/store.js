/**
 * 단일 상태 store.
 * set(patch) 는 실제로 바뀐 키 집합을 구독자에게 넘긴다. 뷰는 자기 deps 와 겹칠 때만 다시 그린다.
 * normalize(next, prev) 는 상태끼리의 규칙(예: 필터에 걸린 선택 해제)을 한 번의 갱신 안에서 적용한다.
 */
export function createStore(initial, normalize = null) {
  let state = { ...initial };
  const listeners = new Set();

  return {
    get state() {
      return state;
    },
    set(patch) {
      let next = { ...state, ...patch };
      if (normalize) next = normalize(next, state);
      const changed = new Set(Object.keys(next).filter((k) => !Object.is(state[k], next[k])));
      if (!changed.size) return;
      state = next;
      for (const fn of listeners) fn(state, changed);
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}
