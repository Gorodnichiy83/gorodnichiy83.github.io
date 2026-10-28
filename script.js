(() => {
  'use strict';
  document.documentElement.classList.add('js');
  const menuButton = document.querySelector('.menu-toggle');
  const navigation = document.querySelector('.navigation');
  const navLinks = [...navigation.querySelectorAll('a')];
  const progress = document.querySelector('.reading-progress');
  const sections = navLinks.map(link => document.querySelector(link.getAttribute('href')));
  const setMenu = open => {
    menuButton.setAttribute('aria-expanded', String(open));
    navigation.classList.toggle('is-open', open);
  };
  menuButton.addEventListener('click', () => setMenu(menuButton.getAttribute('aria-expanded') !== 'true'));
  navLinks.forEach(link => link.addEventListener('click', () => {
    const wasOpen = menuButton.getAttribute('aria-expanded') === 'true';
    setMenu(false);
    if (wasOpen) {
      const target = document.querySelector(link.getAttribute('href'));
      target.setAttribute('tabindex', '-1');
      target.focus({ preventScroll: true });
    }
  }));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menuButton.getAttribute('aria-expanded') === 'true') {
      setMenu(false);
      menuButton.focus();
    }
  });

  let scheduled = false;
  const updateReadingPosition = () => {
    const scrollable = document.documentElement.scrollHeight - innerHeight;
    progress.style.transform = `scaleX(${scrollable > 0 ? Math.max(0, Math.min(1, scrollY / scrollable)) : 0})`;
    let active = -1;
    sections.forEach((section, index) => {
      if (section.getBoundingClientRect().top <= Math.min(innerHeight * .35, 240)) active = index;
    });
    if (scrollable > 0 && scrollY >= scrollable - 4) active = sections.length - 1;
    navLinks.forEach((link, index) => {
      if (index === active) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
    scheduled = false;
  };
  const scheduleUpdate = () => {
    if (!scheduled) {
      scheduled = true;
      requestAnimationFrame(updateReadingPosition);
    }
  };
  window.addEventListener('scroll', scheduleUpdate, { passive: true });
  window.addEventListener('resize', scheduleUpdate);
  window.addEventListener('pageshow', scheduleUpdate);
  document.fonts.ready.then(scheduleUpdate);

  const careerItems = [...document.querySelectorAll('.career-item')];
  const expandCareer = document.querySelector('#expand-career');
  const updateExpandLabel = () => {
    const allOpen = careerItems.every(item => item.open);
    expandCareer.innerHTML = `${allOpen ? 'Свернуть всё' : 'Раскрыть всё'} <span aria-hidden="true">${allOpen ? '−' : '+'}</span>`;
    expandCareer.setAttribute('aria-expanded', String(allOpen));
    scheduleUpdate();
  };
  expandCareer.addEventListener('click', () => {
    const shouldOpen = !careerItems.every(item => item.open);
    careerItems.forEach(item => { item.open = shouldOpen; });
    updateExpandLabel();
  });
  careerItems.forEach(item => item.addEventListener('toggle', updateExpandLabel));
  document.querySelectorAll('.case').forEach(item => item.addEventListener('toggle', scheduleUpdate));

  let printState = null;
  window.addEventListener('beforeprint', () => {
    if (printState) return;
    printState = careerItems.map(item => item.open);
    careerItems.forEach(item => { item.open = true; });
  });
  window.addEventListener('afterprint', () => {
    if (!printState) return;
    careerItems.forEach((item, index) => { item.open = printState[index]; });
    printState = null;
    updateExpandLabel();
  });
  const copyButton = document.querySelector('#copy-email');
  const copyFeedback = document.querySelector('.copy-feedback');
  copyButton.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText('p.gorodnichiy@yandex.ru');
      copyFeedback.textContent = 'Почта скопирована';
    } catch {
      copyFeedback.textContent = 'Выделите и скопируйте адрес: p.gorodnichiy@yandex.ru';
    }
  });
  updateReadingPosition();
})();
