//backToTop button
let backToTop = document.getElementById("btn-back-to-top");

// When the user scrolls down 20px from the top of the document, show the button
window.onscroll = function () {
  scrollFunction();
};

function scrollFunction() {
  if (document.body.scrollTop > 20 || document.documentElement.scrollTop > 20) {
    backToTop.style.display = "block";
  } else {
    backToTop.style.display = "none";
  }
}

// When the user clicks on the button, scroll to the top of the document
backToTop.addEventListener("click", scrollBackToTop);

function scrollBackToTop() {
  document.body.scrollTop = 0;
  document.documentElement.scrollTop = 0;
}



// switch between full/simple results
let switchFullDetail = document.getElementById("switchFullDetail");

function toggleSwitchFullDetail () {
	let addr = new URL(window.location);
	if (addr.pathname.includes("/cat")) {
		// changement de page pour toggle entre full/simple
		if (switchFullDetail.checked == true) {
			pathname = addr.pathname += "detail/";
		} else {
			pathname = addr.pathname.replace("detail/", '');
		}
		window.location.href = addr.origin+pathname+addr.search;
	} else {
		// changement seulement des urls des boutons de catégories
		let listButton = document.querySelectorAll("#linkToCls a");
		listButton.forEach( item => {
			addr = new URL(item.href);
			if (switchFullDetail.checked == true) {
				pathname = addr.pathname += "detail/";
			} else {
				pathname = addr.pathname.replace('detail/', '');
			}
			item.href = pathname + addr.search;
		})
	}
}

switchFullDetail.addEventListener("click", toggleSwitchFullDetail);
