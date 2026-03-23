document.addEventListener('DOMContentLoaded', valuationController)

function valuationController() {
	const wrapper = document.getElementById('main-page-valuation');
	if (!wrapper) {
		console.warn('No main-page-valuation was found found');
		return
	};

	const input = wrapper.querySelector('#gos-number');
	const link = wrapper.querySelector('#gos-number-link');
	const inputMask = wrapper.querySelector('.input-mask');

	if (!input || !link) {
		console.warn('Can\'t find input or link in the main-page-valuation wrapper');
		return;
	}

	inputMask.addEventListener('click', () => {
		input.focus();
	})

	input.addEventListener('input', ({ target }) => {
		let value = target.value.toUpperCase()

		value = value
			.split('')
			.map((char, index) => {
				if (index === 0) {
					return char.match(/[АВЕКМНОРСТУХ]/) ? char : ''
				} else if (index < 4) {
					return char.match(/\d/) ? char : ''
				} else if (index < 6) {
					return char.match(/[АВЕКМНОРСТУХ]/) ? char : ''
				} else {
					return char.match(/\d/) ? char : ''
				}
			})
			.join('')
			.slice(0, 9)

		const inputMaskElements = Array.from(inputMask.querySelectorAll('span'));
		inputMaskElements.forEach((letter, key) => letter.style.opacity = key < value.length ? 0 : 1);

		const regexp = /[АВЕКМНОРСТУХ]\d{3}[АВЕКМНОРСТУХ]{2}\d{2,}/g;

		const isValid = regexp.test(value)
		target.classList.toggle('invalid', !isValid);
		link.classList.toggle('disabled', !isValid);

		target.value = value
		link.href = getGosNumberLink(value);
	})
}

/**
 * Вклеивает госномер в ссылку.
 * Если номер не передан, ссылка не получает параметр.
 * @param {string} number - Госномер
 * @returns {string}
 */
function getGosNumberLink(number) {
	const BUYBACK_PATH = '/buyback/auto_entry';
	const BUYBACK_UTM_PARAMS = 'utm_source=site&utm_medium=main_link_redemption&utm_campaign=main_web';
	return `${window.location.origin}${BUYBACK_PATH}?${number ? `gzn=${number.replace(' ', '')}&` : ''}${BUYBACK_UTM_PARAMS}`;
};
