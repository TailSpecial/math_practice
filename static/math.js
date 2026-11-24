(() => {
  if (typeof window.renderMathInElement !== 'function') return;
  const options = {
    delimiters: [
      {left: '$$', right: '$$', display: true},
      {left: '\\[', right: '\\]', display: true},
      {left: '\\(', right: '\\)', display: false},
      {left: '$', right: '$', display: false},
    ],
    throwOnError: false,
    trust: false,
    maxExpand: 1000,
    maxSize: 20,
    errorColor: '#b3261e',
  };
  const plainTextNodes = element => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, {
      acceptNode: node => node.parentElement.closest('.katex, .katex-error, .matrix-formula, .exponential-formula, code, pre, textarea, script, style')
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    return nodes;
  };
  const renderExponentials = element => {
    for (const node of plainTextNodes(element)) {
      const source = node.textContent;
      const pattern = /\bexp\s*\(\s*([0-9a-zA-Z+\-−*/.^²³\s]{1,128})\s*\)/g;
      const fragment = document.createDocumentFragment();
      let offset = 0;
      let changed = false;
      for (const match of source.matchAll(pattern)) {
        if (!match[1].trim()) continue;
        const exponent = match[1].trim().replace(/−/g, '-').replace(/²/g, '^2').replace(/³/g, '^3').replace(/\*/g, '\\cdot ');
        const formula = document.createElement('span');
        formula.className = 'exponential-formula';
        window.katex.render('e^{' + exponent + '}', formula, {...options, displayMode: false, macros: {}});
        fragment.append(document.createTextNode(source.slice(offset, match.index)), formula);
        offset = match.index + match[0].length;
        changed = true;
      }
      if (changed) {
        fragment.append(document.createTextNode(source.slice(offset)));
        node.replaceWith(fragment);
      }
    }
  };
  // Old tasks contain numeric matrices in Python/JSON notation. Format their
  // display without rewriting the task bank or immutable variant snapshots.
  const renderPlainMatrices = element => {
    for (const node of plainTextNodes(element)) {
      const source = node.textContent;
      const pattern = /\[\s*\[[^\[\]]+\](?:\s*,\s*\[[^\[\]]+\])*\s*\]/g;
      const fragment = document.createDocumentFragment();
      let offset = 0;
      let changed = false;
      for (const match of source.matchAll(pattern)) {
        let rows;
        try { rows = JSON.parse(match[0]); } catch { continue; }
        if (rows.length > 20 || !rows[0].length || rows[0].length > 20 || !rows.every(row =>
          row.length === rows[0].length && row.every(value => typeof value === 'number' && Number.isFinite(value)
            && (!Number.isInteger(value) || Number.isSafeInteger(value))))) continue;
        const preceding = source.slice(offset, match.index);
        const label = preceding.match(/\b([A-Za-z](?:_\d+)?)\s*=\s*$/);
        fragment.append(document.createTextNode(label ? preceding.slice(0, label.index) : preceding));
        const matrix = document.createElement('div');
        matrix.className = 'matrix-formula';
        const number = value => String(value).replace(/e([+-]?\d+)$/, '\\times 10^{$1}');
        const latex = (label ? label[1].replace(/_(\d+)$/, '_{$1}') + ' = ' : '') + '\\begin{bmatrix}'
          + rows.map(row => row.map(number).join(' & ')).join(' \\\\ ') + '\\end{bmatrix}';
        window.katex.render(latex, matrix, {...options, displayMode: true, macros: {}});
        fragment.append(matrix);
        offset = match.index + match[0].length;
        changed = true;
      }
      if (changed) {
        fragment.append(document.createTextNode(source.slice(offset)));
        node.replaceWith(fragment);
      }
    }
  };
  const render = element => {
    window.renderMathInElement(element, {...options, macros: {}});
    renderPlainMatrices(element);
    renderExponentials(element);
  };
  document.querySelectorAll('[data-math]').forEach(render);
  document.querySelectorAll('#id_text, #id_introduction, #id_footer').forEach(field => {
    if (field.tagName !== 'TEXTAREA') return;
    const preview = document.createElement('section');
    preview.className = 'math-preview';
    const heading = document.createElement('div');
    heading.className = 'eyebrow';
    heading.textContent = 'Предпросмотр формул';
    const content = document.createElement('div');
    content.className = 'math-content';
    content.dataset.mathPreview = field.id;
    content.setAttribute('aria-live', 'polite');
    preview.append(heading, content);
    (field.closest('p') || field).after(preview);
    const refresh = () => {
      content.textContent = field.value || 'Введите текст и формулы в поле выше.';
      render(content);
    };
    let timer;
    field.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(refresh, 150);
    });
    refresh();
  });
})();
