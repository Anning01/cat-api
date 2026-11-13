// jsdom has no modal top layer. Browser verification covers native focus/inert behavior.
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function (value = '') {
    this.returnValue = value
    this.open = false
    this.dispatchEvent(new Event('close'))
  }
}
if (!HTMLElement.prototype.scrollIntoView) HTMLElement.prototype.scrollIntoView = function () {}
