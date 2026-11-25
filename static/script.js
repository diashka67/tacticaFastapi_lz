// Весь JavaScript сайта в одном файле.
// Каждый блок работает только если нужные элементы есть на странице.
document.addEventListener('DOMContentLoaded', () => {
  const SESSION_SECONDS = 5 * 60;   // столько же, сколько SESSION_TIMEOUT в file.py

  // 1. Кнопка «показать пароль» у каждого поля пароля
  document.querySelectorAll('input[type="password"]').forEach(input => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pass-toggle';
    btn.textContent = '👁 показать';
    btn.addEventListener('click', () => {
      const hidden = input.type === 'password';
      input.type = hidden ? 'text' : 'password';
      btn.textContent = hidden ? '🙈 скрыть' : '👁 показать';
    });
    input.after(btn);
  });

  // 2. Регистрация: подсказки по паролю в реальном времени
  const regForm = document.querySelector('form[action="/register"]');
  if (regForm) {
    const pw = regForm.elements.password;
    const cf = regForm.elements.confirm;
    const rules = [
      ['минимум 8 символов', (p) => p.length >= 8],
      ['есть буква', (p) => /[A-Za-zА-Яа-яЁё]/.test(p)],
      ['есть цифра', (p) => /\d/.test(p)],
      ['пароли совпадают', (p, c) => p !== '' && p === c],
    ];
    const hint = document.createElement('div');
    hint.className = 'rules';
    regForm.querySelector('button[type="submit"]').before(hint);

    const update = () => {
      hint.innerHTML = rules
        .map(([text, check]) => {
          const ok = check(pw.value, cf.value);
          return `<span class="${ok ? 'ok' : 'bad'}">${ok ? '✔' : '✖'} ${text}</span>`;
        })
        .join('');
    };
    pw.addEventListener('input', update);
    cf.addEventListener('input', update);
    regForm.addEventListener('submit', (e) => {
      if (!rules.every(([, check]) => check(pw.value, cf.value))) {
        e.preventDefault();
        update();
      }
    });
    update();
  }

  // 3. Каталог: мгновенный поиск и фильтр по категориям (без перезагрузки)
  const search = document.getElementById('search');
  const cards = Array.from(document.querySelectorAll('.item'));
  if (search && cards.length) {
    const chips = document.querySelectorAll('.chip');
    const noResults = document.getElementById('no-results');
    const found = document.getElementById('found');
    let category = '';

    const apply = () => {
      const q = search.value.trim().toLowerCase();
      let count = 0;
      cards.forEach(card => {
        const show = (!category || card.dataset.category === category) && card.dataset.text.includes(q);
        card.hidden = !show;
        if (show) count++;
      });
      noResults.hidden = count > 0;
      found.textContent = `Найдено: ${count}`;
    };

    chips.forEach(chip => chip.addEventListener('click', () => {
      category = chip.dataset.category;
      chips.forEach(c => c.classList.toggle('active', c === chip));
      apply();
    }));
    search.addEventListener('input', apply);
    document.getElementById('reset')?.addEventListener('click', () => {
      search.value = '';
      chips[0].click();
    });
    apply();
  }

  // 4. Таймер сессии в шапке: через 5 минут бездействия ведём на страницу входа
  const nav = document.querySelector('.nav');
  if (nav) {
    const timer = document.createElement('span');
    timer.className = 'timer';
    timer.title = 'Сессия закроется через 5 минут без действий';
    nav.prepend(timer);

    let left = SESSION_SECONDS;
    const tick = () => {
      const m = Math.floor(left / 60);
      const s = String(left % 60).padStart(2, '0');
      timer.textContent = `⏳ ${m}:${s}`;
      timer.classList.toggle('warn', left <= 60);
      if (left <= 0) {
        location.href = '/login?expired=1';
        return;
      }
      left--;
    };
    tick();
    setInterval(tick, 1000);
  }

  // 5. Превью картинки перед загрузкой (аватар, картинка предмета)
  document.querySelectorAll('input[type="file"]').forEach(input => {
    const preview = document.createElement('img');
    preview.className = 'preview';
    preview.alt = 'Предпросмотр';
    preview.hidden = true;
    input.after(preview);

    input.addEventListener('change', () => {
      const file = input.files[0];
      if (!file) {
        preview.hidden = true;
        return;
      }
      if (!file.type.startsWith('image/')) {
        alert('Нужна картинка (png, jpg, gif или webp) 🎀');
        input.value = '';
        preview.hidden = true;
        return;
      }
      if (preview.src.startsWith('blob:')) URL.revokeObjectURL(preview.src);
      preview.src = URL.createObjectURL(file);
      preview.hidden = false;
    });
  });

  // 6. Сообщения об успехе сами исчезают через 5 секунд
  document.querySelectorAll('.flash:not(.flash-error)').forEach(el => {
    setTimeout(() => el.classList.add('fade'), 5000);
    setTimeout(() => el.remove(), 5800);
  });

  // 7. Блёстки по клику
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const icons = ['✨', '💖', '🎀', '⭐', '💅'];
    document.addEventListener('click', (e) => {
      const s = document.createElement('span');
      s.className = 'sparkle';
      s.textContent = icons[Math.floor(Math.random() * icons.length)];
      s.style.left = e.pageX + 'px';
      s.style.top = e.pageY + 'px';
      document.body.append(s);
      setTimeout(() => s.remove(), 800);
    });
  }
});
