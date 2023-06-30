import logging

import llama_index
from llama_index import SimpleDirectoryReader
import os

from superagi.jobs.agent_executor import AgentExecutor
from superagi.models.agent_execution import AgentExecution
from superagi.vector_store.embedding.openai import OpenAiEmbedding
from superagi.config.config import get_config


def create_llama_document(file_path: str):
    """
    Creates a document index from a given directory.
    """
    documents = SimpleDirectoryReader(input_files=[file_path]).load_data()


    return documents


def llama_vector_store_factory(vector_store_name, index_name, embedding_model):
    """
    Creates a llama vector store.
    """
    from superagi.vector_store.vector_factory import VectorFactory
    model_api_key = get_config("OPENAI_API_KEY")

    vector_factory_support = ["pinecone", "weaviate"]
    if vector_store_name.lower() in vector_factory_support:
        vector_store = VectorFactory.get_vector_storage(vector_store_name, index_name,
                                                        embedding_model)
        if vector_store_name.lower() == "pinecone":
            from llama_index.vector_stores import PineconeVectorStore
            return PineconeVectorStore(vector_store.index)

        # llama index weaviate doesn't support filtering using metadata
        # if vector_store_name.lower() == "weaviate":
        #     from llama_index.vector_stores import WeaviateVectorStore
        #     print(vector_store.client, "vector_store.client")
        #     return WeaviateVectorStore(vector_store.client)

    if vector_store_name.lower() == "redis":
        redis_url = get_config("REDIS_VECTOR_STORE_URL") or "redis://super__redis:6379"
        from llama_index.vector_stores import RedisVectorStore
        return RedisVectorStore(
            index_name=index_name,
            redis_url=redis_url,
            metadata_fields=["agent_id", "resource_id"]
        )

    if vector_store_name.lower() == "chroma":
        from llama_index.vector_stores import ChromaVectorStore
        import chromadb
        from chromadb.config import Settings
        chroma_client = chromadb.Client(
            Settings(chroma_api_impl="rest", chroma_server_host="chroma", chroma_server_http_port=8000))
        chroma_collection = chroma_client.get_or_create_collection(index_name)
        return ChromaVectorStore(chroma_collection), chroma_collection

    if vector_store_name.lower() == "qdrant":
        from llama_index.vector_stores import QdrantVectorStore
        qdrant_host_name = get_config("QDRANT_HOST_NAME") or "localhost"
        qdrant_port = get_config("QDRANT_PORT") or 6333
        from qdrant_client import QdrantClient
        qdrant_client = QdrantClient(host=qdrant_host_name, port=qdrant_port)
        return QdrantVectorStore(client=qdrant_client, collection_name=index_name)


def save_file_to_vector_store(file_path: str, agent_id: str, resource_id: str):
    from llama_index import VectorStoreIndex
    import openai
    from superagi.vector_store.embedding.openai import OpenAiEmbedding
    from llama_index import StorageContext
    from llama_index import SimpleDirectoryReader
    model_api_key = get_config("OPENAI_API_KEY")
    documents = SimpleDirectoryReader(input_files=[file_path]).load_data()
    for docs in documents:
        if docs.extra_info is None:
            docs.extra_info = {"agent_id": agent_id, "resource_id": resource_id}
        else:
            docs.extra_info["agent_id"] = agent_id
            docs.extra_info["resource_id"] = resource_id
    os.environ["OPENAI_API_KEY"] = get_config("OPENAI_API_KEY")
    vector_store = None
    storage_context = None
    vector_store_name = get_config("RESOURCE_VECTOR_STORE") or "Redis"
    vector_store_index_name = get_config("RESOURCE_VECTOR_STORE_INDEX_NAME") or "super-agent-index"
    try:
        print(vector_store_name, vector_store_index_name)
        vector_store = llama_vector_store_factory(vector_store_name, vector_store_index_name, OpenAiEmbedding(model_api_key))
        if vector_store_name.lower() == "chroma":
            vector_store, chroma_collection = vector_store
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
    except ValueError as e:
        logging.error("Vector store not found",e)
        # vector_store = None
        # vector_store = llama_vector_store_factory('Weaviate', 'super-agent-index1', OpenAiEmbedding(model_api_key))
        # print(vector_store)
        # storage_context = StorageContext.from_defaults(persist_dir="workspace/index")
    openai.api_key = get_config("OPENAI_API_KEY")
    try:
        index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
        index.set_index_id(f'Agent {agent_id}')
    except Exception as e:
        print(e)
    if vector_store_name.lower() == "redis":
        vector_store.persist()
    if vector_store is None:
        index.storage_context.persist(persist_dir="workspace/index")


def generate_summary_of_document(documents: list[llama_index.Document], openai_api_key: str = None):
    openai_api_key = openai_api_key or get_config("OPENAI_API_KEY")
    from llama_index import LLMPredictor
    from llama_index import ServiceContext
    from langchain.chat_models import ChatOpenAI
    from llama_index import ResponseSynthesizer
    from llama_index import DocumentSummaryIndex
    print('aaaaaaaaaaaaaaaaa', openai_api_key)
    os.environ["OPENAI_API_KEY"] = openai_api_key
    llm_predictor_chatgpt = LLMPredictor(llm=ChatOpenAI(temperature=0, model_name="gpt-3.5-turbo",
                                                        openai_api_key=openai_api_key))
    service_context = ServiceContext.from_defaults(llm_predictor=llm_predictor_chatgpt, chunk_size=1024)
    response_synthesizer = ResponseSynthesizer.from_args(response_mode="tree_summarize", use_async=True)
    doc_summary_index = DocumentSummaryIndex.from_documents(
        documents=documents,
        service_context=service_context,
        response_synthesizer=response_synthesizer
    )

    return doc_summary_index.get_document_summary(documents[0].doc_id)


def generate_summary_of_texts(texts: list[str], openai_api_key: str):
    from llama_index import Document
    documents = [Document(doc_id=f"doc_id_{i}", text=text) for i, text in enumerate(texts)]
    return generate_summary_of_document(documents, openai_api_key)
