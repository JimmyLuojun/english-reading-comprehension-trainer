"""Browser script for card translation/note editing, deletion, and pronunciation."""

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

  function deleteWordCard(button) {
    var cardId = button.dataset.deleteWordCard;
    if (!cardId) return;
    var label = button.dataset.deleteLabel || 'this word card';
    if (!window.confirm('Delete "' + label + '" from Cards?')) return;
    button.disabled = true;
    button.textContent = 'Deleting...';
    fetch('/mark/word/' + encodeURIComponent(cardId) + '?return_to=/cards', {
      method: 'DELETE'
    }).then(function (response) {
      if (!response.ok) throw new Error('Delete failed');
      var row = button.closest('tr');
      if (row) row.remove();
    }).catch(function () {
      button.disabled = false;
      button.textContent = 'Delete';
      window.alert('Could not delete this word card.');
    });
  }

  function sentenceFieldElements(sentenceId, field) {
    return {
      text: document.querySelector(
        '.sentence-field-text[data-sentence-id="' + sentenceId + '"][data-sentence-field="' + field + '"]'
      ),
      button: document.querySelector(
        '.sentence-field-edit-btn[data-sentence-id="' + sentenceId + '"][data-sentence-field="' + field + '"]'
      ),
      editor: document.querySelector(
        '.sentence-field-edit[data-sentence-id="' + sentenceId + '"][data-sentence-field="' + field + '"]'
      ),
      input: document.querySelector(
        '.sentence-field-input[data-sentence-id="' + sentenceId + '"][data-sentence-field="' + field + '"]'
      ),
      status: document.querySelector(
        '.sentence-field-status[data-sentence-id="' + sentenceId + '"][data-sentence-field="' + field + '"]'
      )
    };
  }

  function showSentenceFieldEditor(sentenceId, field) {
    var parts = sentenceFieldElements(sentenceId, field);
    if (!parts.input || !parts.editor) return;
    if (parts.status) parts.status.textContent = "";
    if (parts.text) parts.text.style.display = "none";
    if (parts.button) parts.button.style.display = "none";
    parts.editor.hidden = false;
    parts.input.focus();
    parts.input.select();
  }

  function hideSentenceFieldEditor(sentenceId, field) {
    var parts = sentenceFieldElements(sentenceId, field);
    if (!parts.editor) return;
    parts.editor.hidden = true;
    if (parts.text) parts.text.style.display = "";
    if (parts.button) parts.button.style.display = "";
    if (parts.status) parts.status.textContent = "";
  }

  function sentenceFieldSaveRequest(sentenceId, field, value) {
    if (field === "translation") {
      return fetch('/mark/sentence/' + encodeURIComponent(sentenceId) + '/translation', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams({user_translation: value, return_to: '/cards'}).toString()
      });
    }
    return fetch('/mark/sentence/' + encodeURIComponent(sentenceId), {
      method: 'PATCH',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({user_note: value}).toString()
    });
  }

  function saveSentenceField(sentenceId, field) {
    var parts = sentenceFieldElements(sentenceId, field);
    if (!parts.input) return;
    var value = parts.input.value.trim();
    if (field === "translation" && !value) {
      if (parts.status) parts.status.textContent = "Enter a translation first.";
      return;
    }
    if (parts.status) parts.status.textContent = "Saving...";
    sentenceFieldSaveRequest(sentenceId, field, value).then(function (response) {
      if (!response.ok) throw new Error('Save failed');
      if (parts.text) parts.text.textContent = value;
      parts.input.value = value;
      if (parts.text && !value) parts.text.textContent = '—';
      hideSentenceFieldEditor(sentenceId, field);
    }).catch(function () {
      if (parts.status) parts.status.textContent = "Could not save.";
    });
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
    var deleteButton = target.closest ? target.closest('button[data-delete-word-card]') : null;
    if (deleteButton) {
      e.preventDefault();
      deleteWordCard(deleteButton);
      return;
    }
    var sentenceFieldButton = target.closest ? target.closest('.sentence-field-edit-btn') : null;
    if (sentenceFieldButton) {
      e.preventDefault();
      showSentenceFieldEditor(
        sentenceFieldButton.dataset.sentenceId,
        sentenceFieldButton.dataset.sentenceField
      );
      return;
    }
    var sentenceFieldSave = target.closest ? target.closest('.sentence-field-save-btn') : null;
    if (sentenceFieldSave) {
      e.preventDefault();
      saveSentenceField(
        sentenceFieldSave.dataset.sentenceId,
        sentenceFieldSave.dataset.sentenceField
      );
      return;
    }
    var sentenceFieldCancel = target.closest ? target.closest('.sentence-field-cancel-btn') : null;
    if (sentenceFieldCancel) {
      e.preventDefault();
      hideSentenceFieldEditor(
        sentenceFieldCancel.dataset.sentenceId,
        sentenceFieldCancel.dataset.sentenceField
      );
      return;
    }
    if (
      (target.classList.contains('note-text') || target.classList.contains('note-edit-btn')) &&
      target.dataset.cardId
    ) {
      showInput(target.dataset.cardId);
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.target.classList.contains('sentence-field-input')) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        saveSentenceField(e.target.dataset.sentenceId, e.target.dataset.sentenceField);
      }
      if (e.key === 'Escape') {
        hideSentenceFieldEditor(e.target.dataset.sentenceId, e.target.dataset.sentenceField);
      }
      return;
    }
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
