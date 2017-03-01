import numpy as np
from sphericalfield import sphericalfield
from sphere_coefficients import sphere_coefficients
import matplotlib.pyplot as plt
import geometry as g


def map_abs(data):
    return np.hstack(map(np.abs, data[:]))

def check_if_numpy(x, char_x):
    ''' checks if x is a numpy array '''
    if type(x) != np.ndarray:
        print char_x + ' must be an numpy array'
        return False
    else:
        return True

def verbose(data, title, gray = False):
    plt.imshow(data)
    plt.title(title)
    if gray:
        plt.gray()
    plt.show()

def aperture(field, geom, r_max):
    '''Sets field to zero wherever x**2+y**2 >= rmax.'''
    x = geom.xx
    y = geom.yy
    indices = np.where(x**2+y**2 >= r_max**2)
    field[:, indices[0], indices[1]] = 0

    return field

def displacement(s_obj_cart, z, k):
    '''Returns the displacement phase accumulated by an angular spectrum
    propagating a distance z. 
    
    Ref[2]: J. Goodman, Introduction to Fourier Optics, 2nd Edition, 1996
            [See 3.10.2 Propagation of the Angular Spectrum]
    '''

    sxx = s_obj_cart.xx
    syy = s_obj_cart.yy

    inside = sxx**2+syy**2 < 1.
    disp = np.zeros(sxx.shape, dtype = complex)
    disp[inside] = np.exp(1.0j * k * z * np.sqrt( 1. - sxx[inside]**2 - syy[inside]**2))
    return disp

def discretize_plan(NA, M, lamb, nm_img, mpp):
    '''Discretizes a plane according to Eq. 130 - 131.'''

    # Suppose the largest scatterer we consider is 20 lambda. Then
    # P should be larger than 40*NA.
    diam = 400 # wavelengths
    p, q = int(diam*NA), int(diam*NA)

    # Pad with zeros to help dealias and to set del_x to mpp.
    pad_p = int((lamb - mpp*2*NA)/(mpp*2*NA)*p)
    pad_q = int((lamb - mpp*2*NA)/(mpp*2*NA)*q)

    return pad_p, pad_q, p, q

def consv_energy(es, s_obj, s_img, M):
    '''Changes electric field strength factor density to obey the conversation of 
    energy. See Eq. 108 of Ref. 1.
    '''
    return es*-M*np.sqrt(s_img.costheta/s_obj.costheta)

def remove_r(es):
    '''Remove r component of vector.'''
    es[0,:,:] = 0.0
    return es

def propagate_plane_wave(amplitude, k, path_len, shape):
    '''Propagates a plane with wavenumber k through a distance path_len. 
    The wave is polarized in the x direction. The field is given as a 
    cartesian vector field.'''
    e_inc = np.zeros(shape, dtype = complex)
    e_inc[0, :, :] += amplitude*np.exp(-1.j * k * path_len)
    return e_inc

def scatter(s_obj_cart, a_p, n_p, nm_obj, lamb, r, mpp):
    '''Compute the angular spectrum arriving at the entrance pupil.'''
    
    p, q = s_obj_cart.shape

    lamb_m = lamb/np.real(nm_obj)/mpp
    ab = sphere_coefficients(a_p, n_p, nm_obj, lamb)
    sx = s_obj_cart.xx.ravel()
    sy = s_obj_cart.yy.ravel()
    inds = sx**2+sy**2 < 1.

    costheta = np.zeros(sx.shape)
    costheta[inds] = np.sqrt(1. - sx[inds]**2 - sy[inds]**2)

    # Compute the electromagnetic strength factor on the object side 
    # (Eq 40 Ref[1]).
    ang_spec = np.zeros((3,p*q), dtype = complex)
    ang_spec[:,inds] = sphericalfield(sx[inds]*r, sy[inds]*r, costheta[inds]*r, 
                                      ab, lamb_m, cartesian=False, 
                                      str_factor=True)

    return ang_spec.reshape(3, p, q)

def collection(ang_spec, s_obj_cart, s_img_cart, nm_obj, M, r_max):
    '''Compute the angular spectrum leaving the exit pupil.'''

    # Ensure conservation of energy is observed with abbe sine condition.
    es_img = consv_energy(ang_spec, s_obj_cart, s_img_cart, M)
    #es_img = remove_r(es_img) # Should be no r component.

    # Apply aperture. FIXME (MDH): implement.
    #es_img = aperture(es_img, s_img_cart, r_max)
    
    return es_img

def refocus(es_img, s_img, n_disc_grid, p, q, Np, Nq, NA, M, lamb, nm_img,
            aber=None):
    '''Propagates the electric field from the exit pupil to the image plane.'''
    
    if aber is None:
        aber  = np.zeros([3, p, q], complex) 

    # Compute auxiliary (Eq. 133) with zero padding!
    # The lower dimensional s_img.costheta broadcasts to es_img.
    g_aux = es_img * np.exp(-1.j*2*np.pi*aber/lamb) / s_img.costheta 

    # Apply discrete Fourier Transform (Eq. 135).
    es_m_n = np.fft.fft2(g_aux, s = (Np,Nq))
    es_m_n = np.fft.fftshift(es_m_n, axes = (1,2))

    # Compute the electric field at plane 3.
    es_cam  = (1.j*NA**2/(M**2*lamb*nm_img))*(4./(p*q))*es_m_n

    # Accounting for aliasing.
    mm, nn = n_disc_grid.xx, n_disc_grid.yy
    es_cam *= np.exp(-1.j*np.pi*( mm*(1.-p)/Np + nn*(1.-q)/Nq))

    return es_cam

def image_formation(es_cam, e_inc_cam):
    '''Produces an image from the electric fields present.'''
    fields = es_cam + e_inc_cam
    image = np.sum(np.real(fields*np.conjugate(fields)), axis = 0)
    return image

def image_camera_plane(z, a_p, n_p,  nm_obj=1.339, nm_img=1.0, NA=1.45, 
                       lamb=0.447, mpp=0.135, M=100, f=2.E5, dim=[201,201], 
                       quiet=True):
    '''
    Returns an image in the camera plane due to a spherical scatterer with 
    radius a_p and refractive index n_p at a height z above the focal plane. 

    Args:
        z:     [um] scatterer's distance from the focal plane.
        a_p:   [um] sets the radius of the spherical scatterer.
        n_p:   [R.I.U.] sets the refractive index of the scatterer.
        nm_obj:[R.I.U.] sets the refractive index of medium immersing the 
               scattered.
               Default: 1.339 (Water)
        nm_img:[R.I.U.] sets the refractive index of the medium immersing the 
               camera.
               Default: 1.00 (Air)
        NA:    [unitless] The numerical aperture of the optical train.
               Default: 1.45 (100x Nikon Lambda Series)
        lamb:  [um] wavelength of the incident illumination.
               Default: 0.447 (Coherent Cube.. blue)
        mpp:   [um/pix] sets the size of a pixel.
               Default: 0.135.
        M:     [unitless] Magnification of the optical train.
`              Default: 100
        f:     [um]: focal length of the objective. Sets the distance between 
               the entrance
               pupil and the focal plane.
               Default: 20E5 um.
        dim:   [nx, ny]: (will) set the size of the resulting image.
               Default: [201,201]

    Return:
        image: [?, ?] - Currently dim is not implemented. The resulting image 
               size is dictated by the padding chose for the fourier transform.

    Ref[1]: Capoglu et al. (2012). "The Microscope in a Computer:...", 
               Applied Optics, 38(34), 7085.
    '''

    # Necessary constants.
    #k_img = 2*np.pi*nm_img/lamb*mpp # [pix**-1]
    k_obj = 2*np.pi*nm_obj/lamb*mpp # [pix**-1]
    r_max = 100. # [pix]
    sintheta_img = NA/(M*nm_img)

    # Devise a discretization plan.
    pad_p, pad_q, p, q = discretize_plan(NA, M, lamb, nm_img, mpp)
    Np = pad_p + p
    Nq = pad_q + q

    # Compute the three geometries, s_img, s_obj, n_img
    # Origins for the coordinate systems.
    origin = [.5*(p-1.), .5*(q-1.)]
    
    # Scale factors for the coordinate systems.
    img_factor = 2*NA/(M*nm_img)
    obj_factor = 2*NA/nm_obj
    img_scale = [img_factor*1./p, img_factor*1./q]
    obj_scale = [obj_factor*1./p, obj_factor*1./q]

    # Cartesian Geometries.
    # FIXME (MDH): is it necessary to have s_obj_cart?
    s_img_cart = g.CartesianCoordinates(p, q, origin, img_scale)
    s_obj_cart = g.CartesianCoordinates(p, q, origin, obj_scale)
    n_disc_grid = g.CartesianCoordinates(Np, Nq, origin=[.5*(Np-1), .5*(Nq-1.)])
    n_img_cart  = g.CartesianCoordinates(Np, Nq, [.5*(Np-1.), .5*(Nq-1.)], 
                                         img_scale)

    # Spherical Geometries.
    s_obj_cart.acquire_spherical(1.)
    s_img_cart.acquire_spherical(1.)
    n_img_cart.acquire_spherical(1.)

    # 0) Propagate the Incident field to the camera plane.
    e_inc = propagate_plane_wave(-1.0/M, k_obj, z, (3, Np, Nq))
    
    if not quiet:
        verbose(map_abs(e_inc), r'Plane wave at image $(x,y,z)$')

    # 1) Scattering.
    # Compute the angular spectrum incident on entrance pupil of the objective.
    ang_spec = scatter(s_obj_cart, a_p, n_p, nm_obj, lamb, r_max, mpp)
    
    if not quiet:
        verbose(map_abs(ang_spec), r'After Scatter $(r,\theta,\phi)$')

    # 1.5) Displacing the field.
    # Propagate the angular spectrum a distance z_p.
    disp = displacement(s_obj_cart, z, k_obj)
    ang_spec[1:, :] *= disp
    
    if not quiet:
        verbose(np.real(disp), r'Displacement Field')

    # 2) Collection.
    # Compute the electric field strength factor leaving the tube lens.
    es_img = collection(ang_spec, s_obj_cart, s_img_cart, nm_obj, M, 
                        sintheta_img)

    if not quiet:
        verbose(map_abs(es_img), r'After Collection ($r$, $\theta$, $\phi$)')

    # 3) Refocus.
    # Input the electric field strength into the debye-wolf formalism to 
    # compute the scattered field at the camera plane.
    es_img = g.spherical_to_cartesian(es_img, s_img_cart)

    if not quiet:
        verbose(map_abs(es_img), r'Before Refocusing $(x, y, z)$')

    es_cam = refocus(es_img, s_img_cart, n_disc_grid, p, q, Np, Nq, NA, M, lamb,
                     nm_img)
    print('average of es_cam: {}'.format(np.max(image_formation(es_cam, es_cam))))
    if not quiet:
        verbose(map_abs(es_cam), r'After Refocusing $(x, y, z)$')

    # 4) Image formation.
    # Combine the electric fields in the image plane to form an image.
    image = image_formation(es_cam, e_inc)

    return image

def test_discretize():
    NA = 1.45
    M = 100
    lamb = 0.447
    nm_img = 1.0
    mpp = 0.135
    pad_p, pad_q, p, q = discretize_plan(NA, M, lamb, nm_img, mpp)
    
    del_x = lamb*p*M/(2*NA*(pad_p+p))
    print del_x/M

def test_image(z=10.0, quiet=False):
    import matplotlib.pyplot as plt
    from spheredhm import spheredhm

    # Necessary parameters.
    a_p = 0.5
    n_p = 1.5
    mpp = 0.135
    NA = 1.45
    lamb = 0.447
    f = 20.*10**2
    dim = [201,201] # FIXME: Does nothing.
    nm_obj = 1.339
    nm_img = 1.0
    M = 100

    # Produce image with Debye-Wolf Formalism.
    cam_image = image_camera_plane(z/mpp, a_p, n_p,  nm_obj=nm_obj, 
                                   nm_img=nm_img,  NA=NA, lamb=lamb, 
                                   mpp=mpp, M=M, f=f, dim=dim, 
                                   quiet=quiet)

    # Produce image in the focal plane.
    dim = cam_image.shape
    image = spheredhm([0,0, z/mpp], a_p, n_p, nm_obj, dim, mpp, lamb)

    # Visually compare the two.
    diff = M**2*cam_image - image
    print("Maximum difference: {}".format(np.max(diff)))
    verbose(np.hstack([M**2*cam_image, image, diff+1]), 
            r'Camera Plane Image, Focal Plane Image and their Difference.', 
            gray=True)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--quiet', action='store_true', help='If set only plot last figure.')
    parser.add_argument('-z', type=float, help='Height of test particle.', default=10.0)
    args = parser.parse_args()
    test_image(z=args.z, quiet=args.quiet)
