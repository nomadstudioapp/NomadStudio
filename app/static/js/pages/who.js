/* Nomad Studio — "Who's watching?" viewer picker */

(function () {
  const screen = document.getElementById('ns-screen');
  const apiVerify = screen.dataset.apiVerify;
  const apiSelect = screen.dataset.apiSelect;
  const apiCreate = screen.dataset.apiCreate;
  const apiVanish = screen.dataset.apiVanish;
  const goHome = screen.dataset.goHome;
  const goCreate = screen.dataset.goCreate || goHome;

  const pinOverlay   = document.getElementById('ns-pin-overlay');
  const pinAvatarImg = document.getElementById('ns-pin-avatar-img');
  const pinName      = document.getElementById('ns-pin-name');
  const pinDots       = document.querySelectorAll('#ns-pin-dots .ns-dot');
  const pinError      = document.getElementById('ns-pin-error');
  const pinModal      = pinOverlay.querySelector('.ns-modal');

  const addOverlay   = document.getElementById('ns-add-overlay');
  const addName       = document.getElementById('ns-add-name');
  const avatarPicker   = document.getElementById('ns-avatar-picker');
  const pinToggle      = document.getElementById('ns-add-pin-toggle');
  const pinInput        = document.getElementById('ns-add-pin-input');

  let currentPin = '';
  let currentViewerId = null;
  let selectedAvatar = null;

  document.querySelectorAll('.ns-card[data-viewer-id]').forEach(function (card) {
    card.addEventListener('click', function () {
      currentViewerId = card.dataset.viewerId;
      const hasPin = card.dataset.hasPin === 'true';

      if (!hasPin) {
        selectWithoutPin(currentViewerId);
        return;
      }

      pinAvatarImg.src = card.dataset.avatar;
      pinName.textContent = card.dataset.name;
      resetPin();
      openOverlay(pinOverlay);
    });
  });

  function selectWithoutPin(viewerId) {
    fetch(apiSelect, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ viewer_id: viewerId })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) window.location.href = goHome;
      });
  }

  document.querySelectorAll('.ns-key[data-key]').forEach(function (key) {
    key.addEventListener('click', function () {
      if (currentPin.length >= 4) return;
      currentPin += key.dataset.key;
      updatePinDots();
      if (currentPin.length === 4) submitPin();
    });
  });

  document.getElementById('ns-pin-backspace').addEventListener('click', function () {
    currentPin = currentPin.slice(0, -1);
    updatePinDots();
  });

  document.getElementById('ns-pin-cancel').addEventListener('click', function () {
    closeOverlay(pinOverlay);
  });

  function updatePinDots() {
    pinDots.forEach(function (dot, i) {
      dot.classList.toggle('ns-filled', i < currentPin.length);
    });
    pinError.classList.remove('ns-show');
  }

  function resetPin() {
    currentPin = '';
    updatePinDots();
  }

  function submitPin() {
    fetch(apiVerify, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ viewer_id: currentViewerId, pin: currentPin })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          window.location.href = goHome;
        } else {
          pinError.classList.add('ns-show');
          pinModal.classList.add('ns-shake');
          setTimeout(function () { pinModal.classList.remove('ns-shake'); }, 350);
          resetPin();
        }
      })
      .catch(function () {
        pinError.textContent = 'No se pudo verificar el PIN, intenta de nuevo';
        pinError.classList.add('ns-show');
        resetPin();
      });
  }

  const vanishCard = document.getElementById('ns-vanish-viewer');
  if (vanishCard) {
    vanishCard.addEventListener('click', function () {
      if (vanishCard.classList.contains('is-loading')) return;
      vanishCard.classList.add('is-loading');
      fetch(apiVanish, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok) {
            window.location.href = goCreate;
          } else {
            vanishCard.classList.remove('is-loading');
          }
        })
        .catch(function () { vanishCard.classList.remove('is-loading'); });
    });
  }

  document.getElementById('ns-add-viewer').addEventListener('click', function () {
    addName.value = '';
    pinToggle.checked = false;
    pinInput.style.display = 'none';
    pinInput.value = '';
    selectedAvatar = null;
    document.querySelectorAll('.ns-avatar-option').forEach(function (opt) {
      opt.classList.remove('ns-selected');
    });
    openOverlay(addOverlay);
  });

  avatarPicker.addEventListener('click', function (e) {
    const opt = e.target.closest('.ns-avatar-option');
    if (!opt) return;
    document.querySelectorAll('.ns-avatar-option').forEach(function (o) {
      o.classList.remove('ns-selected');
    });
    opt.classList.add('ns-selected');
    selectedAvatar = opt.dataset.avatar;
  });

  pinToggle.addEventListener('change', function () {
    pinInput.style.display = pinToggle.checked ? 'block' : 'none';
  });

  document.getElementById('ns-add-cancel').addEventListener('click', function () {
    closeOverlay(addOverlay);
  });

  document.getElementById('ns-add-save').addEventListener('click', function () {
    const name = addName.value.trim();
    if (!name) { addName.focus(); return; }
    if (!selectedAvatar) { alert('Elige un avatar para el perfil'); return; }

    const pin = pinToggle.checked ? pinInput.value.trim() : null;
    if (pinToggle.checked && pin.length !== 4) {
      alert('El PIN debe tener 4 dígitos');
      return;
    }

    fetch(apiCreate, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, avatar: selectedAvatar, pin: pin })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          window.location.reload();
        } else {
          alert(data.error || 'No se pudo crear el perfil');
        }
      });
  });

  function openOverlay(el) { el.classList.add('ns-open'); }
  function closeOverlay(el) { el.classList.remove('ns-open'); }

  [pinOverlay, addOverlay].forEach(function (overlay) {
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) closeOverlay(overlay);
    });
  });
})();
