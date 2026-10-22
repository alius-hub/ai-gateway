import type { ObjectDirective } from "vue";

type Close = () => void;
type State = { close: Close; startedOutside: boolean; cleanup: () => void };
const states = new WeakMap<HTMLElement, State>();

export const backdropClose: ObjectDirective<HTMLElement, Close> = {
  mounted(el, binding) {
    const state: State = { close: binding.value, startedOutside: false, cleanup: () => {} };
    const down = (event: PointerEvent) => {
      state.startedOutside = event.target === el && event.button === 0 && event.isPrimary;
    };
    const cancel = () => { state.startedOutside = false; };
    const click = (event: MouseEvent) => {
      const shouldClose = state.startedOutside && event.target === el;
      state.startedOutside = false;
      if (shouldClose) state.close();
    };
    el.addEventListener("pointerdown", down, true);
    el.addEventListener("pointercancel", cancel, true);
    el.addEventListener("click", click);
    state.cleanup = () => {
      el.removeEventListener("pointerdown", down, true);
      el.removeEventListener("pointercancel", cancel, true);
      el.removeEventListener("click", click);
    };
    states.set(el, state);
  },
  updated(el, binding) {
    const state = states.get(el);
    if (state) state.close = binding.value;
  },
  unmounted(el) {
    states.get(el)?.cleanup();
    states.delete(el);
  },
};
