"""Browser script for card note editing and pronunciation."""

from __future__ import annotations

def _def_edit_script() -> str:
    return """
(function () {
  var pronunciationVoice = null;

  function supportsSpeech() {
    return 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
  }

  function pickPronunciationVoice() {
    if (!supportsSpeech()) return null;
    var voices = window.speechSynthesis.getVoices();
    pronunciationVoice =
      voices.find(function (voice) { return voice.name === 'Samantha'; }) ||
      voices.find(function (voice) { return voice.name === 'Google US English'; }) ||
      voices.find(function (voice) { return voice.lang === 'en-US'; }) ||
      voices[0] ||
      null;
    return pronunciationVoice;
  }

  function disablePronunciationButtons() {
    document.querySelectorAll('button[data-speak-text]').forEach(function (button) {
      button.disabled = true;
      button.title = 'Pronunciation unavailable';
    });
  }

  function speakText(text) {
    var value = (text || '').trim();
    if (!value || !supportsSpeech()) return;
    var utterance = new SpeechSynthesisUtterance(value);
    utterance.lang = 'en-US';
    utterance.rate = 0.9;
    utterance.voice = pronunciationVoice || pickPronunciationVoice();
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }

  if (supportsSpeech()) {
    pickPronunciationVoice();
    window.speechSynthesis.addEventListener('voiceschanged', pickPronunciationVoice);
  } else {
    disablePronunciationButtons();
  }

  function showInput(cardId) {
    var span = document.querySelector('.note-text[data-card-id="' + cardId + '"]');
    var btn  = document.querySelector('.note-edit-btn[data-card-id="' + cardId + '"]');
    var inp  = document.querySelector('.note-input[data-card-id="' + cardId + '"]');
    if (!inp) return;
    span.style.display = 'none';
    btn.style.display  = 'none';
    inp.style.display  = '';
    inp.focus();
    inp.select();
  }
  function saveInput(cardId) {
    var span = document.querySelector('.note-text[data-card-id="' + cardId + '"]');
    var btn  = document.querySelector('.note-edit-btn[data-card-id="' + cardId + '"]');
    var inp  = document.querySelector('.note-input[data-card-id="' + cardId + '"]');
    if (!inp) return;
    var newVal = inp.value.trim();
    var body = new URLSearchParams({
      current_meaning: inp.dataset.currentMeaning || '',
      user_note: newVal
    });
    fetch('/mark/word/' + cardId, { method: 'PATCH', body: body })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          span.textContent = newVal || '—';
          inp.value = newVal;
        }
      });
    span.style.display = '';
    btn.style.display  = '';
    inp.style.display  = 'none';
  }
  document.addEventListener('click', function (e) {
    var target = e.target;
    var speakButton = target.closest ? target.closest('button[data-speak-text]') : null;
    if (speakButton) {
      e.preventDefault();
      speakText(speakButton.dataset.speakText || '');
      return;
    }
    if (target.classList.contains('note-text') || target.classList.contains('note-edit-btn')) {
      showInput(target.dataset.cardId);
    }
  });
  document.addEventListener('keydown', function (e) {
    if (!e.target.classList.contains('note-input')) return;
    if (e.key === 'Enter')  { e.preventDefault(); saveInput(e.target.dataset.cardId); }
    if (e.key === 'Escape') {
      var cardId = e.target.dataset.cardId;
      var span = document.querySelector('.note-text[data-card-id="' + cardId + '"]');
      var btn  = document.querySelector('.note-edit-btn[data-card-id="' + cardId + '"]');
      e.target.style.display = 'none';
      span.style.display = '';
      btn.style.display  = '';
    }
  });
  document.addEventListener('focusout', function (e) {
    if (e.target.classList.contains('note-input')) {
      saveInput(e.target.dataset.cardId);
    }
  });
}());
"""
