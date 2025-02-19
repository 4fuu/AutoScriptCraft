import gradio as gr
from fpdf import FPDF

import logging
import tempfile
import asyncio

from roleplay.core import get_role
from roleplay.core import load_llm
from roleplay.stream import load_roles_from_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

def stream_fn(message, tag):
    if tag == 'end':
        suffix = '-------------'
        print('\n' + suffix, end='', flush=True)
        return
    if (message.additional_kwargs):
        print(message.additional_kwargs.get("reasoning_content") or '',
              end='', flush=True)
    print(message.content, end='', flush=True)

class State:
    def __init__(self):
        self.is_stop = False
        self._input = '无'
        self.require = '无'
        self.story = '无'
        self.story_cnt = -1
        self.story_node = -1
        self.character = '无'
        self.script = '无'
        self.total_tokens = 0
        self.current_state = '任务未开始'
        self.roles_name = {}
        load_llm("./llms/deepseek.llm.yaml")
        for role in load_roles_from_dir("./roles"):
            role.set_stream_fn(stream_fn) #type:ignore

    def generate_pdf(self):
        """生成包含所有内容的PDF文件"""
        pdf = FPDF()

        font_path = "./asset/京華老宋体.TTF"
        pdf.add_font("KingHwa_OldSong", "", font_path, uni=True)
        pdf.set_font("KingHwa_OldSong", size=14)

        # 封面页
        pdf.add_page()
        pdf.cell(200, 10, text="剧本生成报告", ln=True, align='C')
        pdf.ln(20)

        # 数据概览
        pdf.cell(200, 10, text="1. 数据概览", ln=True)
        pdf.multi_cell(0, 10, text=f"""用户输入：{self._input}
总Token数：{self.total_tokens}
剧本字数：{len(self.script)}
生成状态：{self.current_state}""")
        pdf.ln(10)

        # 需求清单
        pdf.add_page()
        pdf.cell(200, 10, text="2. 需求清单", ln=True)
        pdf.multi_cell(0, 10, text=self.require)
        pdf.ln(10)

        # 剧情节点
        pdf.cell(200, 10, text="3. 剧情节点", ln=True)
        pdf.multi_cell(0, 10, text=self.story)
        pdf.ln(10)

        # 角色设定
        pdf.add_page()
        pdf.cell(200, 10, text="4. 角色设定", ln=True)
        pdf.multi_cell(0, 10, text=self.character)
        pdf.ln(10)

        # 最终剧本
        pdf.cell(200, 10, text="5. 完整剧本", ln=True)
        pdf.multi_cell(0, 10, text=self.script)

        # 生成临时文件
        _, temp_path = tempfile.mkstemp(suffix=".pdf")
        pdf.output(temp_path)

        return temp_path

    def get_role(self, name):
        self.roles_name[name] = 1
        return get_role(name)

    def get_token(self):
        _token = 0
        for name, _ in self.roles_name.items():
            _token += get_role(name).parser.total_tokens
        self.total_tokens = _token

    def stop(self,):
        self.current_state = '任务被用户终止'
        self.is_stop = True

    def clear(self):
        # self.is_stop = False
        self._input = '无'
        self.require = '无'
        self.story = '无'
        self.story_cnt = -1
        self.story_node = -1
        self.character = '无'
        self.script = '无'
        self.total_tokens = 0
        self.current_state = '任务未开始'
        self.roles_name = {}

    async def start(self, message, progress=gr.Progress()):
        self.is_stop = False
        self.clear()
        self._input = message

        yield progress(0, desc="生成中")
        self.current_state = '正在生成需求...'

        ret = await asyncio.to_thread(self.get_role('demand').run, require=message)
        self.get_token()
        yield progress(1/9, desc="需求生成完成")

        self.current_state = '格式化需求...'
        ret = await asyncio.to_thread(self.get_role('demand-format').run,
                                      require=self._input + '\n' + ret['output'].content)
        self.get_token()
        self.require = self._input + '\n' + ret['output'].content
        yield progress(2/9, desc="需求格式化完成")

        ret = await self.node2()
        if not ret:
            return
        self.get_token()
        yield progress(3/9, desc="剧情节点生成完成")

        ret = await self.node3(ret['output'].content)
        self.get_token()
        yield progress(4/9, desc="剧情节点格式化完成")

        await self.node4()
        self.get_token()
        yield progress(5/9, desc="剧情节点计数完成")

        await self.node4_5()
        self.get_token()
        yield progress(6/9, desc="剧情节点编号格式化完成")

        ret = await self.node5()
        if not ret:
            return
        self.get_token()
        yield progress(7/9, desc="角色生成完成")

        await self.node6(ret['output'].content)
        self.get_token()
        yield progress(8/9, desc="角色格式化完成")

        yield progress(8.5/9, desc="正在生成最终剧本...")
        await self.node7()
        self.get_token()
        self.current_state = '生成结束'

        yield progress(9/9, desc="成功")
        await asyncio.sleep(1)

    async def node2(self):
        if self.is_stop:
            return
        self.current_state = '生成关键剧情节点...'
        return await asyncio.to_thread(self.get_role('story').run, require=self.require)

    async def node3(self, story):
        if self.is_stop:
            return
        self.current_state = '格式化剧情节点...'
        ret = await asyncio.to_thread(self.get_role('story-format').run, story=story)
        self.story = ret['output'].content

    async def node4(self):
        if self.is_stop:
            return
        self.current_state = '计数剧情节点...'
        ret = await asyncio.to_thread(self.get_role('story-cnt').run, story=self.story)
        self.story_cnt = int(ret['output'].content)

    async def node4_5(self):
        if self.is_stop:
            return
        self.current_state = '再次格式化剧情节点...'
        ret = await asyncio.to_thread(self.get_role('story-format1').run,
                                      story=self.story,
                                      story_cnt=self.story_cnt)
        self.story = ret['output'].content

    async def node5(self):
        if self.is_stop:
            return
        self.current_state = '生成角色...'
        return await asyncio.to_thread(self.get_role('character').run,
                                       require=self.require,
                                       story=self.story)

    async def node6(self, character):
        if self.is_stop:
            return
        self.current_state = '格式化角色...'
        ret = await asyncio.to_thread(self.get_role('character-format').run,
                                      character=character)
        self.character = ret['output'].content

    async def node7(self):
        self.script = ''
        for i in range(self.story_cnt):
            self.story_node = i + 1
            c = 'script'
            if i > 20:
                c = 'script-chat'
            self.current_state = f'生成剧情节点[{self.story_node}]...'
            ret = await asyncio.to_thread(self.get_role(c).run,
                                          require=self.require,
                                          story=self.story,
                                          character=self.character,
                                          story_node=str(self.story_node),
                                          script=self.script)
            self.script += ret['output'].content + '\n\n'
            self.get_token()

    def get_mk_format(self):
        return f'''
你的输入：{self._input}
1. 已使用token：{self.total_tokens}
2. 当前状态：{self.current_state}
3. 剧本字数：{len(self.script)}
''', self.require, self.story, self.character, self.script

state = State()

with gr.Blocks(title='剧本生成') as demo:
    gr.Markdown("# 剧本生成")
    with gr.Row():
        with gr.Column(scale=2) as show:
            with gr.Accordion('数据',):
                md1 = gr.Markdown()
            with gr.Accordion('需求清单',):
                md2 = gr.Markdown()
            with gr.Accordion('剧情节点',):
                md3 = gr.Markdown()
            with gr.Accordion('角色设定',):
                md4 = gr.Markdown()
            with gr.Accordion('剧本',):
                md5 = gr.Markdown()
        with gr.Column(scale=1) as chat:
            msg = gr.Textbox(label="输入需求", lines=20)
            button = gr.Button("开始")
            button1 = gr.Button("停止")
            download_btn = gr.DownloadButton("下载剧本PDF")
            button.click(state.start, inputs=[msg], outputs=[msg])
            button1.click(state.stop)
            download_btn.click(
                fn=lambda: state.generate_pdf(),
                outputs=gr.File(label="剧本报告.pdf"),
            )
    async def update_mkd():
        while True:
            yield [gr.Markdown(mk) for mk in state.get_mk_format()]
            await asyncio.sleep(1)
    demo.load(
        fn=update_mkd,
        outputs=[md1, md2, md3, md4, md5],
        show_api=False,
        show_progress='hidden'
    )

demo.queue().launch(server_name='0.0.0.0')
