const btnDefault = document.getElementById('btn-default');
const defaultScript = btnDefault.dataset.default;
const input = document.getElementById('command-input');
const btnRun = document.getElementById('btn-run');
const btnStop = document.getElementById('btn-stop');
const btnClear = document.getElementById('btn-clear');
const btnCopy = document.getElementById('btn-copy');
const output = document.getElementById('output');
const autoScrollToggle = document.getElementById('auto-scroll');
let currentTaskId = null;
let eventSource = null;

function appendOutput(chunk) {
    const div = document.createElement('div');
    div.className = 'output-line';
    div.textContent = chunk;
    output.appendChild(div);
    if (autoScrollToggle.checked && output.scrollHeight) {
        output.scrollTop = output.scrollHeight;
    }
}

function clearOutput() {
    output.innerHTML = '';
}

function setRunning(running) {
    btnRun.disabled = running;
    btnDefault.disabled = running;
    btnStop.disabled = !running;
}

async function startTask(mode, value) {
    clearOutput();
    try {
        const res = await fetch('/api/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode, value })
        });
        const data = await res.json();
        if (!data.success) {
            appendOutput(`[error] ${data.error.message || '执行失败'}`);
            return;
        }
        currentTaskId = data.task_id;
        setRunning(true);
        streamOutput(currentTaskId);
    } catch (err) {
        appendOutput(`[error] ${err}`);
    }
}

function streamOutput(taskId) {
    if (eventSource) {
        eventSource.close();
    }
    eventSource = new EventSource(`/api/stream/${taskId}`);
    eventSource.onmessage = (event) => {
        appendOutput(event.data);
    };
    eventSource.onerror = () => {
        eventSource.close();
        setRunning(false);
    };
}

async function stopTask() {
    if (!currentTaskId) return;
    await fetch(`/api/stop/${currentTaskId}`, { method: 'POST' });
    setRunning(false);
    if (eventSource) eventSource.close();
}

btnDefault.addEventListener('click', () => startTask('script', defaultScript));
btnRun.addEventListener('click', () => {
    const value = input.value.trim();
    if (!value) {
        appendOutput('[system] 请输入脚本路径或命令');
        return;
    }
    const mode = value.startsWith('/') ? 'script' : 'command';
    startTask(mode, value);
});
btnStop.addEventListener('click', stopTask);
btnClear.addEventListener('click', clearOutput);
btnCopy.addEventListener('click', async () => {
    const text = Array.from(output.childNodes).map(n => n.textContent).join('\n');
    try {
        await navigator.clipboard.writeText(text);
        appendOutput('[system] 输出已复制');
    } catch (err) {
        appendOutput('[error] 无法复制: ' + err);
    }
});

output.addEventListener('wheel', () => {
    const nearBottom = output.scrollTop + output.clientHeight >= output.scrollHeight - 20;
    if (!nearBottom) {
        autoScrollToggle.checked = false;
    }
});
