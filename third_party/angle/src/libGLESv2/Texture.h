//
// Copyright (c) 2002-2013 The ANGLE Project Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//

// Texture.h: Defines the abstract gl::Texture class and its concrete derived
// classes Texture2D and TextureCubeMap. Implements GL texture objects and
// related functionality. [OpenGL ES 2.0.24] section 3.7 page 63.

#ifndef LIBGLESV2_TEXTURE_H_
#define LIBGLESV2_TEXTURE_H_

#include <vector>

#include "angle_gl.h"

#include "common/debug.h"
#include "common/RefCountObject.h"
#include "libGLESv2/angletypes.h"
#include "libGLESv2/constants.h"
#include "libGLESv2/renderer/TextureImpl.h"

namespace egl
{
class Surface;
}

namespace rx
{
class TextureStorageInterface;
class RenderTarget;
class Image;
}

namespace gl
{
class Framebuffer;
class FramebufferAttachment;

class Texture : public RefCountObject
{
  public:
    Texture(GLuint id, GLenum target);

    virtual ~Texture();

    GLenum getTarget() const;

    const SamplerState &getSamplerState() const { return mSamplerState; }
    SamplerState &getSamplerState() { return mSamplerState; }
    void getSamplerStateWithNativeOffset(SamplerState *sampler);

    void setUsage(GLenum usage);
    GLenum getUsage() const;

    GLint getBaseLevelWidth() const;
    GLint getBaseLevelHeight() const;
    GLint getBaseLevelDepth() const;
    GLenum getBaseLevelInternalFormat() const;

    bool isSamplerComplete(const SamplerState &samplerState) const;

    rx::TextureStorageInterface *getNativeTexture();

    virtual void generateMipmaps();
    virtual void copySubImage(GLenum target, GLint level, GLint xoffset, GLint yoffset, GLint zoffset, GLint x, GLint y, GLsizei width, GLsizei height, Framebuffer *source);

    unsigned int getTextureSerial();

    bool isImmutable() const;
    int immutableLevelCount();

    virtual rx::TextureImpl *getImplementation() = 0;
    virtual const rx::TextureImpl *getImplementation() const = 0;

    static const GLuint INCOMPLETE_TEXTURE_ID = static_cast<GLuint>(-1);   // Every texture takes an id at creation time. The value is arbitrary because it is never registered with the resource manager.

  protected:
    int mipLevels() const;

    SamplerState mSamplerState;
    GLenum mUsage;

    bool mImmutable;

    GLenum mTarget;

  private:
    DISALLOW_COPY_AND_ASSIGN(Texture);

    const rx::Image *getBaseLevelImage() const;
};

class Texture2D : public Texture
{
  public:
    Texture2D(rx::Texture2DImpl *impl, GLuint id);

    ~Texture2D();

    GLsizei getWidth(GLint level) const;
    GLsizei getHeight(GLint level) const;
    GLenum getInternalFormat(GLint level) const;
    GLenum getActualFormat(GLint level) const;
    bool isCompressed(GLint level) const;
    bool isDepth(GLint level) const;

    void setImage(GLint level, GLsizei width, GLsizei height, GLenum internalFormat, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);
    void setCompressedImage(GLint level, GLenum format, GLsizei width, GLsizei height, GLsizei imageSize, const void *pixels);
    void subImage(GLint level, GLint xoffset, GLint yoffset, GLsizei width, GLsizei height, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);
    void subImageCompressed(GLint level, GLint xoffset, GLint yoffset, GLsizei width, GLsizei height, GLenum format, GLsizei imageSize, const void *pixels);
    void copyImage(GLint level, GLenum format, GLint x, GLint y, GLsizei width, GLsizei height, Framebuffer *source);
    void storage(GLsizei levels, GLenum internalformat, GLsizei width, GLsizei height);

    virtual void bindTexImage(egl::Surface *surface);
    virtual void releaseTexImage();

    virtual void generateMipmaps();

    unsigned int getRenderTargetSerial(GLint level);

    virtual rx::TextureImpl *getImplementation() { return mTexture; }
    virtual const rx::TextureImpl *getImplementation() const { return mTexture; }

  protected:
    friend class Texture2DAttachment;
    rx::RenderTarget *getRenderTarget(GLint level);
    rx::RenderTarget *getDepthStencil(GLint level);

  private:
    DISALLOW_COPY_AND_ASSIGN(Texture2D);

    rx::Texture2DImpl *mTexture;
    egl::Surface *mSurface;
};

class TextureCubeMap : public Texture
{
  public:
    TextureCubeMap(rx::TextureCubeImpl *impl, GLuint id);

    ~TextureCubeMap();

    GLsizei getWidth(GLenum target, GLint level) const;
    GLsizei getHeight(GLenum target, GLint level) const;
    GLenum getInternalFormat(GLenum target, GLint level) const;
    GLenum getActualFormat(GLenum target, GLint level) const;
    bool isCompressed(GLenum target, GLint level) const;
    bool isDepth(GLenum target, GLint level) const;

    void setImagePosX(GLint level, GLsizei width, GLsizei height, GLenum internalFormat, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);
    void setImageNegX(GLint level, GLsizei width, GLsizei height, GLenum internalFormat, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);
    void setImagePosY(GLint level, GLsizei width, GLsizei height, GLenum internalFormat, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);
    void setImageNegY(GLint level, GLsizei width, GLsizei height, GLenum internalFormat, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);
    void setImagePosZ(GLint level, GLsizei width, GLsizei height, GLenum internalFormat, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);
    void setImageNegZ(GLint level, GLsizei width, GLsizei height, GLenum internalFormat, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);

    void setCompressedImage(GLenum target, GLint level, GLenum format, GLsizei width, GLsizei height, GLsizei imageSize, const void *pixels);

    void subImage(GLenum target, GLint level, GLint xoffset, GLint yoffset, GLsizei width, GLsizei height, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);
    void subImageCompressed(GLenum target, GLint level, GLint xoffset, GLint yoffset, GLsizei width, GLsizei height, GLenum format, GLsizei imageSize, const void *pixels);
    void copyImage(GLenum target, GLint level, GLenum format, GLint x, GLint y, GLsizei width, GLsizei height, Framebuffer *source);
    void storage(GLsizei levels, GLenum internalformat, GLsizei size);

    bool isCubeComplete() const;

    unsigned int getRenderTargetSerial(GLenum target, GLint level);

    static int targetToLayerIndex(GLenum target);
    static GLenum layerIndexToTarget(GLint layer);

    virtual rx::TextureImpl *getImplementation() { return mTexture; }
    virtual const rx::TextureImpl *getImplementation() const { return mTexture; }

  protected:
    friend class TextureCubeMapAttachment;
    rx::RenderTarget *getRenderTarget(GLenum target, GLint level);
    rx::RenderTarget *getDepthStencil(GLenum target, GLint level);

  private:
    DISALLOW_COPY_AND_ASSIGN(TextureCubeMap);

    rx::TextureCubeImpl *mTexture;
};

class Texture3D : public Texture
{
  public:
    Texture3D(rx::Texture3DImpl *impl, GLuint id);

    ~Texture3D();

    GLsizei getWidth(GLint level) const;
    GLsizei getHeight(GLint level) const;
    GLsizei getDepth(GLint level) const;
    GLenum getInternalFormat(GLint level) const;
    GLenum getActualFormat(GLint level) const;
    bool isCompressed(GLint level) const;
    bool isDepth(GLint level) const;

    void setImage(GLint level, GLsizei width, GLsizei height, GLsizei depth, GLenum internalFormat, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);
    void setCompressedImage(GLint level, GLenum format, GLsizei width, GLsizei height, GLsizei depth, GLsizei imageSize, const void *pixels);
    void subImage(GLint level, GLint xoffset, GLint yoffset, GLint zoffset, GLsizei width, GLsizei height, GLsizei depth, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);
    void subImageCompressed(GLint level, GLint xoffset, GLint yoffset, GLint zoffset, GLsizei width, GLsizei height, GLsizei depth, GLenum format, GLsizei imageSize, const void *pixels);
    void storage(GLsizei levels, GLenum internalformat, GLsizei width, GLsizei height, GLsizei depth);

    unsigned int getRenderTargetSerial(GLint level, GLint layer);

    virtual rx::TextureImpl *getImplementation() { return mTexture; }
    virtual const rx::TextureImpl *getImplementation() const { return mTexture; }

  protected:
    friend class Texture3DAttachment;
    rx::RenderTarget *getRenderTarget(GLint level, GLint layer);
    rx::RenderTarget *getDepthStencil(GLint level, GLint layer);

  private:
    DISALLOW_COPY_AND_ASSIGN(Texture3D);

    rx::Texture3DImpl *mTexture;
};

class Texture2DArray : public Texture
{
  public:
    Texture2DArray(rx::Texture2DArrayImpl *impl, GLuint id);

    ~Texture2DArray();

    GLsizei getWidth(GLint level) const;
    GLsizei getHeight(GLint level) const;
    GLsizei getLayers(GLint level) const;
    GLenum getInternalFormat(GLint level) const;
    GLenum getActualFormat(GLint level) const;
    bool isCompressed(GLint level) const;
    bool isDepth(GLint level) const;

    void setImage(GLint level, GLsizei width, GLsizei height, GLsizei depth, GLenum internalFormat, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);
    void setCompressedImage(GLint level, GLenum format, GLsizei width, GLsizei height, GLsizei depth, GLsizei imageSize, const void *pixels);
    void subImage(GLint level, GLint xoffset, GLint yoffset, GLint zoffset, GLsizei width, GLsizei height, GLsizei depth, GLenum format, GLenum type, const PixelUnpackState &unpack, const void *pixels);
    void subImageCompressed(GLint level, GLint xoffset, GLint yoffset, GLint zoffset, GLsizei width, GLsizei height, GLsizei depth, GLenum format, GLsizei imageSize, const void *pixels);
    void storage(GLsizei levels, GLenum internalformat, GLsizei width, GLsizei height, GLsizei depth);

    unsigned int getRenderTargetSerial(GLint level, GLint layer);

    virtual rx::TextureImpl *getImplementation() { return mTexture; }
    virtual const rx::TextureImpl *getImplementation() const { return mTexture; }

  protected:
    friend class Texture2DArrayAttachment;
    rx::RenderTarget *getRenderTarget(GLint level, GLint layer);
    rx::RenderTarget *getDepthStencil(GLint level, GLint layer);

  private:
    DISALLOW_COPY_AND_ASSIGN(Texture2DArray);

    rx::Texture2DArrayImpl *mTexture;
};

}

#endif   // LIBGLESV2_TEXTURE_H_
