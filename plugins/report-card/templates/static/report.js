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
  });
})();
