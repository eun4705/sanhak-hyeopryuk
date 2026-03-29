// content script: 페이지 컨텍스트에 스크립트 주입
const s1 = document.createElement('script');
s1.src = chrome.runtime.getURL('scraper.js');
(document.head || document.documentElement).appendChild(s1);

const s2 = document.createElement('script');
s2.src = chrome.runtime.getURL('scraper_universal.js');
(document.head || document.documentElement).appendChild(s2);

const s3 = document.createElement('script');
s3.src = chrome.runtime.getURL('scraper_health.js');
(document.head || document.documentElement).appendChild(s3);

const s4 = document.createElement('script');
s4.src = chrome.runtime.getURL('scan_annuity.js');
(document.head || document.documentElement).appendChild(s4);

const s5 = document.createElement('script');
s5.src = chrome.runtime.getURL('scraper_annuity.js');
(document.head || document.documentElement).appendChild(s5);
