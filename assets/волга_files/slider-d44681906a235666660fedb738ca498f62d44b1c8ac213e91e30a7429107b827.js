class Slider {
  /**
   * Constructs a new Slider instance.
   *
   * @param {Object} options - Configuration options for the slider.
   */
  constructor({
    bannerWrapperSelector = '.banner',
    bannerContentSelector = '#banner-content',
    slideIndicatorsSelector = '#slide-indicators',
    slideControlsSelector = '.slider-controls',
    slideSelector = '.slide',
    indicatorSelector = '.slide-indicators__indicator',
    intervalTime = 4000,
  } = {}) {
    this.bannerContent = document.querySelector(bannerContentSelector);
    this.bannerWrapper = document.querySelector(bannerWrapperSelector);
    this.slideIndicators = document.querySelector(slideIndicatorsSelector);
    this.sliderControls = document.querySelector(slideControlsSelector);
    this.slides = Array.from(document.querySelectorAll(slideSelector));
    this.indicators = Array.from(document.querySelectorAll(indicatorSelector));
    this.interval = intervalTime;
    this.threshold = 30;

    this.initBannerLinks();


    this.slideIndicators.addEventListener('click', (event) => {
      if (event.target.type === 'button') this.captionHandler(event);
    });

    this.sliderControls.addEventListener('click', (event) => {
      if (event.target.type === 'button') this.controlsHandler(event);
    });

    this.bannerWrapper.addEventListener('touchstart', (event) => {
      this.touchStartX = event.touches[0].clientX;
    });

    this.bannerWrapper.addEventListener('touchend', (event) => {
      this.swipeHandler(event);
    });
  }

  /**
   * Starts the slideshow at the specified index.
   *
   * @param {number} startIndex - The start index.
   */
  startSlideshow(startIndex = 0) {
    this.gotoSlide(startIndex, true);
  }

  /**
   * Responds to a click on the slide indicator by going to the slide.
   *
   * @param {Event} event - The click event.
   */
  captionHandler(event) {
    const button = event.target;
    this.gotoSlide(Number(button.value), true);
  }

  /**
   * Responds to a click on a slide control by going to the next or previous slide.
   *
   * @param {Event} event - The click event.
   */
  controlsHandler(event) {
    const currentIndex = this.currentIndex;

    if (event.target.value === 'next')
      this.gotoSlide(this.nextIndex(currentIndex), true);
    else if (event.target.value === 'prev')
      this.gotoSlide(this.prevIndex(currentIndex), true);
  }

  /**
   * Responds to a swipe by going to the next or previous slide.
   *
   * @param {Event} event - The touchend event.
   */
  swipeHandler(event) {
    if (
      this.touchStartX &&
      Math.abs(this.touchStartX - event.changedTouches[0].clientX) >
        this.threshold
    ) {
      this.touchStartX > event.changedTouches[0].clientX
        ? this.gotoSlide(this.nextIndex(this.currentIndex), true)
        : this.gotoSlide(this.prevIndex(this.currentIndex), true);
    }
    this.touchStartX = null;
  }

  /**
   * Goes to the specified slide.
   *
   * @param {number} index - The slide index.
   * @param {boolean} restartTimer - Whether to restart the timer.
   */
  gotoSlide(index, restartTimer = false) {
    if (this.intervalID) {
      clearInterval(this.intervalID);
      this.intervalID = null;
    }

    this.currentIndex = index;
    this.bannerContent.scrollTo({
      left: this.slides[0].offsetWidth * index,
      behavior: 'smooth',
    });
    this.updateIndicators(index);

    if (restartTimer) {
      this.intervalID = setInterval(
        () => this.gotoSlide(this.nextIndex(this.currentIndex), true),
        this.interval
      );
    }
  }

  /**
   * Updates the slide indicators to reflect the current slide.
   *
   * @param {number} activeIndex - The index of the active slide.
   */
  updateIndicators(activeIndex) {
    this.indicators.forEach((indicator, index) => {
      indicator.classList.toggle('active', index === activeIndex);
      indicator.setAttribute('aria-selected', index === activeIndex);
    });
  }

  /**
   * Returns the index of the next slide.
   *
   * @param {number} currentIndex - The index of the current slide.
   */
  nextIndex(currentIndex) {
    return currentIndex === this.slides.length - 1 ? 0 : currentIndex + 1;
  }

  /**
   * Returns the index of the previous slide.
   *
   * @param {number} currentIndex - The index of the current slide.
   */
  prevIndex(currentIndex) {
    return currentIndex === 0 ? this.slides.length - 1 : currentIndex - 1;
  }

  initBannerLinks() {
    const links = document.querySelectorAll('.bannerLink');

    links.forEach(link => {
      link.addEventListener('click', (event) => {
        const bannerId = event.target.getAttribute('data-id');
        const bannerName = event.target.getAttribute('data-name');
        this.sendBannerDataToGTM(bannerId, bannerName);
      });
    });
  }

  sendBannerDataToGTM(bannerId, bannerName) {
    const bannerLocation = window.location.pathname;
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({
      event: 'banner_click',
      event_params: {
        id: bannerId,
        location: bannerLocation,
        name: bannerName,
      },
    });
  }
}

const bannerSlider = new Slider();
bannerSlider.startSlideshow();
