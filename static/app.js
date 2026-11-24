(() => {
  const master = document.querySelector('[data-select-all]');
  if (!master) return;
  const boxes = [...document.querySelectorAll('input[name="students"][form="bulk-allocation"]')];
  const counter = document.querySelector('[data-selection-count]');
  const button = document.querySelector('[data-bulk-submit]');
  const refresh = () => {
    const count = boxes.filter(box => box.checked).length;
    master.checked = boxes.length > 0 && count === boxes.length;
    master.indeterminate = count > 0 && count < boxes.length;
    master.disabled = boxes.length === 0;
    counter.textContent = count ? `Выбрано студентов: ${count}` : 'Выберите студентов в таблице';
    button.disabled = count === 0;
  };
  master.addEventListener('change', () => {
    boxes.forEach(box => { box.checked = master.checked; });
    refresh();
  });
  boxes.forEach(box => box.addEventListener('change', refresh));
  refresh();
})();
