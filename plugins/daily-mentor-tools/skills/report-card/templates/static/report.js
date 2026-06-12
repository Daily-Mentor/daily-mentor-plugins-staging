// Minimal vanilla JS for tab switching + Daily Tracker month filter.
(function(){
  function activate(name){
    document.querySelectorAll('nav.rc-tabs button').forEach(b => {
      b.classList.toggle('active', b.dataset.tab === name);
    });
    document.querySelectorAll('section.tab-panel').forEach(s => {
      s.classList.toggle('active', s.dataset.tab === name);
    });
  }

  // Final Report Card: tint a row green/red from its pass/fail status glyph.
  function toneRow(tr){
    if (!tr || !tr.closest('section[data-tab="final_report_card"]')) return;
    tr.classList.remove('row-pass','row-fail');
    if (tr.querySelector('.status-fail, .mentor-status.fail')) tr.classList.add('row-fail');
    else if (tr.querySelector('.status-pass, .mentor-status.pass')) tr.classList.add('row-pass');
  }
  function initRowTones(){
    document.querySelectorAll('section[data-tab="final_report_card"] table.rc-table tbody tr').forEach(toneRow);
  }

  // Mentor-entered benchmark inputs: compare the typed value to its target live,
  // flip the sibling status cell ✓/✗, and persist to localStorage.
  function evalMentor(input){
    const key = input.dataset.mentorKey;
    const status = document.querySelector('.mentor-status[data-mentor-status="' + (window.CSS && CSS.escape ? CSS.escape(key) : key) + '"]');
    const raw = input.value.trim();
    const target = parseFloat(input.dataset.target);
    if (status){ status.classList.remove('pass','fail'); }
    if (raw === '' || isNaN(parseFloat(raw))){
      if (status){ status.textContent = '—'; toneRow(status.closest('tr')); }
      return;
    }
    const val = parseFloat(raw);
    if (!isNaN(target)){
      const ok = input.dataset.dir === 'max' ? (val <= target) : (val >= target);
      if (status){ status.textContent = ok ? '✓' : '✗'; status.classList.add(ok ? 'pass' : 'fail'); toneRow(status.closest('tr')); }
    }
  }
  function initMentor(){
    document.querySelectorAll('input.mentor-input').forEach(input => {
      const sk = 'mentor:' + input.dataset.mentorKey;
      try { const saved = localStorage.getItem(sk); if (saved !== null) input.value = saved; } catch(e){}
      evalMentor(input);
      input.addEventListener('input', () => {
        try { localStorage.setItem(sk, input.value); } catch(e){}
        evalMentor(input);
      });
    });
  }
  // Expand/collapse: section headers fold their group; expandable account rows
  // toggle their vendor/SKU sub-rows (collapsed by default).
  function initCollapse(){
    document.querySelectorAll('tr.expandable').forEach(tr => {
      tr.addEventListener('click', () => {
        const key = tr.dataset.expandKey;
        const open = tr.classList.toggle('open');
        tr.closest('table').querySelectorAll('tr[data-sub-of]').forEach(s => {
          if (s.dataset.subOf === key) s.classList.toggle('hidden-by-parent', !open);
        });
      });
    });
    document.querySelectorAll('tr.section').forEach(sec => {
      sec.addEventListener('click', () => {
        const collapsed = sec.classList.toggle('collapsed');
        let n = sec.nextElementSibling;
        while (n && !n.classList.contains('section')){
          n.classList.toggle('hidden-by-section', collapsed);
          n = n.nextElementSibling;
        }
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function(){
    document.querySelectorAll('nav.rc-tabs button').forEach(b => {
      b.addEventListener('click', () => activate(b.dataset.tab));
    });
    // First tab default
    const first = document.querySelector('nav.rc-tabs button');
    if (first) activate(first.dataset.tab);
    initMentor();
    initCollapse();
    initRowTones();
  });
})();
