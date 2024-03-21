

function fallbackCopyTextToClipboard(text) {
    var textArea = document.createElement("textarea");
    textArea.value = text;

    // Avoid scrolling to bottom
    textArea.style.top = "0";
    textArea.style.left = "0";
    textArea.style.position = "fixed";

    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();

    try {
        var successful = document.execCommand('copy');
        var msg = successful ? 'successful' : 'unsuccessful';
        console.log('Fallback: Copying text command was ' + msg);
    } catch (err) {
        console.error('Fallback: Oops, unable to copy', err);
    }

    document.body.removeChild(textArea);
}
function copyTextToClipboard(text) {
    if (!navigator.clipboard) {
        fallbackCopyTextToClipboard(text);
        return;
    }
    navigator.clipboard.writeText(text).then(function () {
        console.log('Async: Copying to clipboard was successful!');
    }, function (err) {
        console.error('Async: Could not copy text: ', err);
    });
}

function copyEventListener(e) {
    console.log(e);
    var text = e.target.getAttribute('data-copy');
    copyTextToClipboard(text);
    var message = e.target.parentNode.querySelector('.copy-text-to-clipboard-message');
    message.classList.add('show');
    setTimeout(function () {
        message.classList.remove('show');
    }, 500);

}

document.addEventListener('DOMContentLoaded', function () {
    var elements = document.querySelectorAll('.copy-text-to-clipboard-icon');
    for (var i = 0; i < elements.length; i++) {
        elements[i].addEventListener('click', copyEventListener, false);
    }
});
