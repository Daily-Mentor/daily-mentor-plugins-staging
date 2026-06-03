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

  // Mentor-entered benchmark inputs: compare the typed value to its target live,
  // flip the sibling status cell ✓/✗, and persist to localStorage.
  function evalMentor(input){
    const key = input.dataset.mentorKey;
    const status = document.querySelector('.mentor-status[data-mentor-status="' + (window.CSS && CSS.escape ? CSS.escape(key) : key) + '"]');
    const raw = input.value.trim();
    const target = parseFloat(input.dataset.target);
    if (status){ status.classList.remove('pass','fail'); }
    if (raw === '' || isNaN(parseFloat(raw))){
      if (status){ status.textContent = '—'; }
      return;
    }
    const val = parseFloat(raw);
    if (!isNaN(target)){
      const ok = input.dataset.dir === 'max' ? (val <= target) : (val >= target);
      if (status){ status.textContent = ok ? '✓' : '✗'; status.classList.add(ok ? 'pass' : 'fail'); }
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
  document.addEventListener('DOMContentLoaded', function(){
    document.querySelectorAll('nav.rc-tabs button').forEach(b => {
      b.addEventListener('click', () => activate(b.dataset.tab));
    });
    // First tab default
    const first = document.querySelector('nav.rc-tabs button');
    if (first) activate(first.dataset.tab);
    // Month pills (Daily Tracker)
    document.querySelectorAll('.month-pills').forEach(group => {
      const target = group.dataset.target;
      group.querySelectorAll('button').forEach(b => {
        b.addEventListener('click', () => {
          group.querySelectorAll('button').forEach(x => x.classList.toggle('active', x === b));
          document.querySelectorAll('[data-tracker-month]').forEach(t => {
            t.style.display = t.dataset.trackerMonth === b.dataset.month ? '' : 'none';
          });
        });
      });
      // Activate first
      const first = group.querySelector('button');
      if (first) first.click();
    });
    initMentor();
  });
})();
