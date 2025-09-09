// CoCon Vote Monitor
// votes.js
// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 3P Technologies Srl
// Author: Marco Miano

'use strict';

const main = document.getElementById('votes');
const meetingEl = document.getElementById('meeting-title');
const agendaEl = document.getElementById('agenda-title');
const dateEl = document.getElementById('datetime');
const footerEl = document.querySelector('footer');
const yesCnt = document.querySelector('.vote.footer.yes  .vote-count');
const abtCnt = document.querySelector('.vote.footer.abst .vote-count');
const noCnt = document.querySelector('.vote.footer.no   .vote-count');
// Auto-print on the default route. Disable when visiting `/noautoprint`.
const autoPrint = !window.location.pathname.startsWith('/noautoprint');
let printed = false;

function buildColumns(columns = []) {
  const frag = document.createDocumentFragment();
  for (const col of columns) {
    const colDiv = document.createElement('div');
    colDiv.className = 'column';
    for (const [delegate, result] of col) {
      const voteDiv = document.createElement('div');
      voteDiv.className = 'vote ' + (result ?? '').toLowerCase();

      const resDiv = document.createElement('div');
      resDiv.className = 'vote-result';
      resDiv.textContent = result; // delegate name

      const labDiv = document.createElement('div');
      labDiv.className = 'vote-label';
      labDiv.textContent = delegate || ''; // YES / NO / ABST / ''

      voteDiv.append(resDiv, labDiv);
      colDiv.appendChild(voteDiv);
    }
    frag.appendChild(colDiv);
  }
  return frag;
}

function update(data) {
  document.title = data.title
  meetingEl.textContent = data.meeting_title ?? '';
  agendaEl.textContent = data.agenda_title ?? '';
  dateEl.textContent = data.datetime ?? '';
  main.replaceChildren(buildColumns(data.columns));
  yesCnt.textContent = data.counts?.YES ?? 0;
  abtCnt.textContent = data.counts?.ABST ?? 0;
  noCnt.textContent = data.counts?.NO ?? 0;
  footerEl.style.display = data.show_results ? 'flex' : 'none';
  if (autoPrint && data.voting_state === 'Stop' && !printed) {
    printed = true;
    window.print();
  }
  if (data.voting_state !== 'Stop') {
    printed = false;
  }
}

const ws = new WebSocket(`ws://${location.host}/ws`);
ws.onmessage = evt => update(JSON.parse(evt.data));
