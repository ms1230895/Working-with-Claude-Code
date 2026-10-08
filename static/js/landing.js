// landing.js — "See how it works" video modal

const modal = document.getElementById('how-it-works-modal');
const openButton = document.getElementById('how-it-works-open');
const closeButton = modal.querySelector('.video-modal-close');
const frame = modal.querySelector('.video-modal-frame');
const videoTemplate = frame.querySelector('template');

openButton.addEventListener('click', () => {
    // The player is only on the page while the modal is open.
    frame.append(videoTemplate.content.cloneNode(true));
    modal.showModal();
});

closeButton.addEventListener('click', () => modal.close());

// The dialog has no padding, so a click that lands on the dialog element
// itself (not on something inside it) is a click on the backdrop.
modal.addEventListener('click', (event) => {
    if (event.target === modal) modal.close();
});

// Runs for the close button, a backdrop click and the Esc key.
// Removing the player from the page is what stops the video.
modal.addEventListener('close', () => {
    frame.querySelector('iframe').remove();
});
