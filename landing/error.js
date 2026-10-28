/* Touchstone — error page behaviour.
   The shell is the landing page's (bar, burger, footer), but the example engine
   stays off this page: #report, #counts and friends don't exist here, and
   landing.js would throw on them. This file carries only what the shell needs,
   mirroring landing.js's hamburger block. */

(() => {
  'use strict';

  // Marks that JS is running: the CSS uses html.js to collapse the nav into a
  // hamburger. Without a script the section links simply stay visible.
  document.documentElement.classList.add('js');

  const burger = document.querySelector('#nav-burger');
  const barIn = document.querySelector('.bar-in');
  if (!(burger && barIn)) return;

  const setMenu = (open) => {
    barIn.classList.toggle('menu-open', open);
    burger.setAttribute('aria-expanded', open ? 'true' : 'false');
  };
  burger.addEventListener('click', () => setMenu(!barIn.classList.contains('menu-open')));
  document.querySelectorAll('#site-nav a').forEach((a) => a.addEventListener('click', () => setMenu(false)));
  addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && barIn.classList.contains('menu-open')) { setMenu(false); burger.focus(); }
  });
})();
