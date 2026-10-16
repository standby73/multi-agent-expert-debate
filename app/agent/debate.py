
import os
import sys
from typing import Any, Dict
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.agents import LlmAgent, SequentialAgent, ParallelAgent, LoopAgent
from google.adk.tools.tool_context import ToolContext
from google.adk.agents.callback_context import CallbackContext
from pydantic import BaseModel, Field
from mcp import StdioServerParameters

from maikol_utils.print_utils import print_warn, print_color

from config import Configuration



def create_debate_agent(CONFIG: Configuration, agents_config: list):
    """
    Create a debate agent system dynamically based on the provided agents configuration.
    
    Args:
        agents_config: List of agent configurations from DEBATES
        
    Returns:
        SequentialAgent: The root agent for the debate system
    """
    # Ensure max_tokens is valid (at least 1, typically much higher)
    max_tokens = min(2048, CONFIG.max_tokens) if CONFIG.max_tokens else 2048
    
    model_config = LiteLlm(
        model=CONFIG.model, 
        api_base=CONFIG.api_base, 
        api_key=CONFIG.api_key,
        max_tokens=max_tokens,
        # Add explicit parameters to avoid auto-calculation issues
        drop_params=True  # Drop unsupported params instead of failing
    )
    # ============================================================
    # 1) AGENTES EXPERTOS (Posturas Opuestas)
    # ============================================================
    agents = [
        LlmAgent(
            model=model_config,
            **agent
        ) for agent in agents_config
    ]

    visiones_iniciales = ParallelAgent(
        name="visiones_iniciales",
        sub_agents=agents,
        description="Cada experto expone su visión inicial sobre el tema."
    )

    # ============================================================
    # 2) FASE DE DEBATE DINÁMICO (Loop)
    # ============================================================

    herramienta_escritura = McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=[os.path.join("mcp","write.py")],
                env={
                    **os.environ.copy(),  
                    "LOGS_PATH": CONFIG.log_path,
                }
            )
        )
    )

    # ============================================================
    # AGENTES DE GESTIÓN DE CONTEXTO
    # ============================================================
    
    # Agente que resume la iteración anterior para reducir contexto
    agente_resumen = LlmAgent(
        name="agente_resumen_contexto",
        model=model_config,
        instruction=(
            "Eres un asistente de resumen. Tu tarea es crear un resumen CONCISO de la iteración de debate anterior.\n"
            "REQUISITOS:\n"
            "1. Resume en máximo 400 palabras los puntos principales discutidos\n"
            "2. Identifica las áreas de acuerdo y desacuerdo\n"
            "3. No repitas argumentos completos, solo menciona los temas clave de forma que des contexto a cada agente de por donde iba en el debate\n"
            "4. Formato: '**RESUMEN ITERACIÓN ANTERIOR**: [tu resumen aquí]'\n"
            "5. Dar contexto de por donde iba el debate de forma general y cada agente por separado para que no pierda el hilo."
            "Si es la primera iteración, responde: '**RESUMEN ITERACIÓN ANTERIOR**: Primera iteración, sin historial previo.'"
        ),
        output_key="resumen_iteracion_anterior"
    )

    # ============================================================
    # AGENTES EXPERTOS CON CONTEXTO LIMITADO
    # ============================================================

    replicas_dinamicas = []

    for agent_info in agents_config:
        r_agent = LlmAgent(
            name=f"replica_{agent_info['name']}",
            model=model_config,
            instruction=(
                f"Eres {agent_info['name']}. {agent_info.get('instruction', '')}\n\n"
                "**TU TAREA (máximo 150 palabras):**\n"
                "1. Argumenta tu posición de forma directa como el experto que eres\n"
                "2. Responde a los puntos clave del debate actual\n"
                "3. Indica claramente: ¿Estás dispuesto a ceder? ¿En qué sí y en qué no?\n"
                "4. IMPORTANTE: NO escribas meta-comentarios tipo 'El usuario pregunta...' o 'Necesito responder...'\n"
                "5. Habla DIRECTAMENTE en primera persona\n\n"
                "Ejemplo: 'Defiendo que... porque... Estoy dispuesto a ceder en... pero no en...'"
            ),
            output_key=f"output_replica_{agent_info['name']}"
        )
        replicas_dinamicas.append(r_agent)

    # El Mediador analiza el intercambio y redacta un borrador de acuerdo
    mediador_consenso = LlmAgent(
        name="mediador_consenso",
        model=model_config,
        instruction=(
            "Eres el Mediador del debate. Analiza las posturas de los expertos.\n\n"
            "**TU TAREA (máximo 200 palabras):**\n"
            "1. Identifica:\n"
            "   - ¿En qué puntos HAY acuerdo?\n"
            "   - ¿Dónde persiste el desacuerdo?\n"
            "2. Propone una solución de compromiso ESPECÍFICA y CONCRETA\n"
            "3. Indica CLARAMENTE: ¿HAY CONSENSO SUFICIENTE? SÍ o NO\n"
            "4. Si SÍ hay consenso, redacta el ACUERDO FINAL detalladamente\n\n"
            "IMPORTANTE:\n"
            "- NO escribas 'el usuario' o 'debo analizar'\n"
            "- Escribe DIRECTAMENTE: 'Los expertos acordaron que...'\n"
            "- Sé específico y concreto en el acuerdo final"
        ),
        output_key="borrador_consenso"
    )



    # ============================================================
    # TOOL: exit_loop - Para detener el ciclo de debate
    # ============================================================
    
    def exit_loop(tool_context: ToolContext):
        """Call this function ONLY when consensus has been reached and the debate should end."""
        print(f"  [Tool Call] exit_loop triggered by {tool_context.agent_name}")
        tool_context.actions.escalate = True
        return {}

    class ConsensoSchema(BaseModel):
        done: bool = Field(description="Si hay consenso real y específico")
        feedback: str = Field(description="Razón breve del estado del consenso")

    # El Revisor decide si el borrador es lo suficientemente bueno
    revisor = LlmAgent(
        name="revisor",
        model=model_config,
        instruction=(
            "Analiza el 'borrador_consenso' para decidir si hay CONSENSO REAL.\n\n"
            "CRITERIOS para consenso:\n"
            "1. Los expertos llegaron a un acuerdo específico y concreto\n"
            "2. El borrador describe claramente QUÉ se decidió\n"
            "3. No quedan desacuerdos fundamentales\n\n"
            "ACCIONES:\n"
            "- Si HAY CONSENSO: Llama a 'exit_loop' Y responde {\"done\": true, \"feedback\": \"Consenso: [breve descripción]\"}\n"
            "- Si NO hay consenso: Solo responde {\"done\": false, \"feedback\": \"[razón breve]\"}\n\n"
            "Sé ESTRICTO: solo hay consenso si el acuerdo es claro y específico."
        ),
        output_key="estado_consenso",
        output_schema=ConsensoSchema,
        tools=[exit_loop]
    )

    # Unimos todo en el bucle: primero resumimos, luego debatimos
    ciclo_debate = LoopAgent(
        name="ciclo_debate",
        sub_agents=[agente_resumen, *replicas_dinamicas, mediador_consenso, revisor],
        max_iterations=CONFIG.ciclo_debate_max_iterations,
        description="Los expertos debaten de forma iterativa con contexto limitado para evitar sobrecarga.",
    )

    # ============================================================
    # 3) AGENTE MODERADOR (Documento Final)
    # ============================================================
    def check_report_callback(callback_context: CallbackContext, *, llm_request = None, **kwargs):
        """
        Revisa el informe final generado por el moderador para asegurar que cumple con la estructura requerida.
        """
        documento_final = callback_context.output.get('documento_final_md', '') if hasattr(callback_context, 'output') else ''
        print_color(f"\n[Moderador Final] Documento generado:---\n{documento_final}\n---", color="cyan")


        expected_sections = [
            "# TEMA DEBATIDO",
            "## RESUMEN DEL PROCESO",
            "## DECISIÓN CONSENSUADA",
            "## RECOMENDACIÓN FINAL JUSTIFICADA"
        ]

        missing_sections = [sec for sec in expected_sections if sec not in documento_final]
        if missing_sections:
            print_warn(f"[Moderador Final] ERROR: Faltan secciones en el informe final: {missing_sections}")
        else:
            print_color(f"[Moderador Final] Informe final verificado correctamente.", color="green")


    moderador_final = LlmAgent(
        name="moderador_final",
        model=model_config,
        description="Redacta el informe de consenso final en formato Markdown.",
        instruction=(
            "Eres el Secretario del Debate. Redacta el ACTA FINAL en español.\n\n"
            "ENTRADA: Tienes acceso al 'borrador_consenso' del mediador.\n\n"
            "TAREA: Crea un documento Markdown completo (mínimo 300 palabras) con esta estructura EXACTA. HAZLO SE HAYA LLEGADO AUN ACUERDO O NO:\n\n"
            "# TEMA DEBATIDO\n"
            "[Describe claramente cuál fue la pregunta o tema debatido. Explica el contexto y por qué es importante. 2-3 párrafos]\n\n"
            "## RESUMEN DEL PROCESO\n"
            "[Resume el debate:\n"
            "- Cuántas iteraciones se realizaron\n"
            "- Qué posturas iniciales presentaron los expertos\n"
            "- Cómo evolucionó el debate (qué argumentos surgieron, qué concesiones se hicieron)\n"
            "- El tono y la calidad del intercambio\n"
            "3-4 párrafos detallados]\n\n"
            "## DECISIÓN CONSENSUADA\n"
            "[SI HAY CONSENSO: Detalla el acuerdo final específico:\n"
            "- Qué se decidió exactamente\n"
            "- Bajo qué condiciones o circunstancias aplica\n"
            "- Qué compromisos aceptaron los expertos\n"
            "- Áreas de acuerdo alcanzadas\n\n"
            "SI NO HAY CONSENSO: Explica:\n"
            "- Por qué no se alcanzó consenso\n"
            "- Cuáles fueron los puntos de desacuerdo irreconciliables\n"
            "- Qué posiciones mantuvieron los expertos\n"
            "- Qué intentos de compromiso se propusieron pero no prosperaron\n\n"
            "3-4 párrafos detallados]\n\n"
            "## RECOMENDACIÓN FINAL JUSTIFICADA\n"
            "[SI HAY CONSENSO: Justifica por qué esta decisión consensuada es razonable y equilibrada:\n"
            "- Qué criterios satisface\n"
            "- Cómo equilibra los diferentes puntos de vista\n"
            "- Qué beneficios aporta\n\n"
            "SI NO HAY CONSENSO: Propone:\n"
            "- Qué pasos adicionales serían necesarios para alcanzar acuerdo\n"
            "- Qué información o análisis adicional se requiere\n"
            "- Posibles caminos para futuras deliberaciones\n"
            "- Recomendaciones para los tomadores de decisión dado el desacuerdo\n\n"
            "2-3 párrafos justificados]\n\n"
            "REGLAS CRÍTICAS:\n"
            "- DEBES incluir las 4 secciones con encabezados EXACTOS tal como aparecen arriba\n"
            "- SIEMPRE escribe contenido completo en todas las secciones, haya o no consenso\n"
            "- Mínimo 2-3 párrafos por sección\n"
            "- NO incluyas saludos ni firmas\n"
            "- NO escribas meta-comentarios\n"
            "- Escribe el acta DIRECTAMENTE como documento formal y objetivo en el campo documento_final_md"
        ),
        output_key="documento_final_md",
        after_model_callback=check_report_callback
    )

    agente_escritor = LlmAgent(
        name="agente_escritor",
        model=model_config,
        tools=[herramienta_escritura],
        description="Guarda físicamente el acta en el sistema de archivos.",
        instruction=(
            "Eres un Agente de Sistema para guardar archivos.\n\n"
            "INSTRUCCIONES:\n"
            "1. Tienes acceso a 'documento_final_md' con el acta completa\n"
            "2. Llama INMEDIATAMENTE a 'escribir_archivo' con:\n"
            "   - nombre_archivo: 'acta_consenso_final.md'\n"
            "   - contenido: TODO el texto de 'documento_final_md'\n"
            "3. NO modifiques el contenido\n"
            "4. NO generes texto nuevo\n"
            "5. Llama la herramienta UNA SOLA VEZ\n\n"
            "Si no ves 'documento_final_md', responde: 'ERROR: No hay documento para guardar'"
        )
    )

    # ============================================================
    # PIPELINE ROOT
    # ============================================================

    root_agent = SequentialAgent(
        name="sistema_debate_consenso",
        sub_agents=[visiones_iniciales, ciclo_debate, moderador_final, agente_escritor],
        description="Flujo completo de debate autónomo y generación de consenso."
    )
    return root_agent