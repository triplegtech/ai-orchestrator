---
name: aio
description: Envia uma tarefa de desenvolvimento para o ai-orchestrator (LangGraph + agentes Claude Code) no repositório atual e resume o relatório ao final.
argument-hint: "<tarefa em linguagem natural> [--check \"cmd\"] [--allow-path glob] [--with design|devops]"
disable-model-invocation: true
allowed-tools: Bash(aio *), Bash(git -C * diff *), Read
---

# /aio — tarefa autônoma via ai-orchestrator

O usuário quer delegar esta tarefa para a equipe de agentes: $ARGUMENTS

1. Rode, a partir da pasta do projeto atual, com o Bash em **segundo plano** (`run_in_background: true`;
   a tarefa leva vários minutos):

   ```
   aio run "<tarefa>" [opções que o usuário passou]
   ```

   - O texto da tarefa vai entre aspas duplas; escape aspas duplas internas.
   - Repasse `--check`, `--allow-path`, `--with`, `--base` e `--repo` exatamente como o usuário escreveu.
     Não invente comandos de `--check`: o orquestrador detecta a stack e prepara o ambiente sozinho.
     Não acrescente `--with` por conta própria: o planner decide quando consultar design ou devops.
   - Diga ao usuário, em uma linha, que a tarefa foi enviada e que você avisa quando terminar.

2. Quando o comando terminar, leia o `report.md` cujo caminho aparece na linha `Relatório:` da saída
   e responda de forma curta:
   - resultado (`done`, `blocked` ou `awaiting_approval`) e, se bloqueado, o motivo;
   - arquivos alterados e comandos de validação com exit code;
   - especialistas consultados (design/devops), se houver, e os passos manuais que eles apontaram;
   - veredito do revisor (critérios atendidos e problemas apontados);
   - tentativas e custo;
   - o branch `agents/<task-id>` e o comando `git diff` do relatório para revisar.

3. Se o resultado for `awaiting_approval` (exit 3), a alteração toca CI/CD e nada foi commitado.
   Rode o comando `git -C ... diff -- ...` da seção "Aguardando aprovação" do relatório, mostre o diff
   ao usuário e pergunte se aprova. Só depois da resposta dele rode, em segundo plano,
   `aio approve <task-id>` ou `aio reject <task-id>` e resuma o resultado como no passo 2.
   Nunca aprove por conta própria.

4. Nunca faça merge, push, nem apague o branch ou o worktree sem o usuário pedir explicitamente.
   Se o usuário pedir o merge, mostre o diff primeiro.

5. Se a tarefa ficou bloqueada por preparação do ambiente ou por falta de comando de validação,
   sugira o próximo passo concreto (por exemplo, um `--check` específico para este projeto).
