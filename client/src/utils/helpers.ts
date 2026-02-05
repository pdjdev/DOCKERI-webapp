export function escapeHtml(str: string): string {
  return String(str).replace(/[&<>"]+/g, (s) => {
    const map: Record<string, string> = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
    };
    return map[s] || s;
  });
}

export function scrollToBottom(element: HTMLElement | null) {
  if (element) {
    element.scrollTop = element.scrollHeight;
  }
}
